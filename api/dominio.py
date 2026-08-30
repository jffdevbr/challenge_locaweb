"""Carga das tabelas, montagem das 9 séries e classificação da data escolhida.

As séries são montadas exatamente como em `model_training.ipynb` (§2.2/§2.3) — `soma7` sobre o
histórico inteiro antes do recorte, grupo `total` com as razões reconstruídas de numerador e
denominador somados. Qualquer desvio aqui faz a previsão deixar de bater com a camada gold, e o
teste de reprodução existe para pegar isso.

Tudo é carregado uma vez, no startup, e fica em memória: são ~19 MB.
"""

from functools import lru_cache

import numpy as np
import pandas as pd

from api import config as cfg


# ==================================================================================================
# Carga das tabelas
# ==================================================================================================

def _ler(caminho, **kwargs):
    return pd.read_csv(caminho, sep=";", parse_dates=["data"], **kwargs)


class Dominio:
    """Estado carregado: tabelas, séries por (grupo, prioridade) e o manifesto dos modelos."""

    def __init__(self):
        self.fato = _ler(cfg.CAMINHO_SILVER / "s_fato_diario_prioridade.csv")
        self.calendario = _ler(cfg.CAMINHO_SILVER / "s_dim_calendario.csv")
        self.ola = _ler(cfg.CAMINHO_SILVER / "s_fato_ola_prioridade.csv")
        self.turno = _ler(cfg.CAMINHO_SILVER / "s_fato_diario_prioridade_turno.csv")
        self.previsoes_gold = _ler(cfg.CAMINHO_GOLD / "g_previsoes.csv")
        self.avaliacao = pd.read_csv(cfg.CAMINHO_GOLD / "g_avaliacao_modelos.csv", sep=";")
        self.manifesto = pd.read_csv(cfg.CAMINHO_MODELOS / "manifesto.csv", sep=";")

        self.fato = self.fato[self.fato.prioridade.isin(cfg.PRIORIDADES)].copy()
        self.calendario_janela = _calendario_janela(self.calendario)
        self.series = _montar_series(self.fato, self.calendario, self.calendario_janela)

        # O calendário vai até 2026-12-31, além do fim da série. É dele que sai a exógena futura
        # quando a origem é o último dia do histórico — a série não teria essas linhas.
        self.calendario_completo = (self.calendario.merge(self.calendario_janela, on="data",
                                                          how="left")
                                    .set_index("data").sort_index())

        self.data_min = self.fato.data.min()
        self.data_max = self.fato.data.max()

    # -- acesso ------------------------------------------------------------------------------
    def serie(self, grupo, prioridade):
        return self.series[(grupo, prioridade)]

    def calendario_em(self, datas, colunas):
        """Valores de calendário para uma lista de datas — inclusive datas além da série."""
        if not colunas:
            return None
        faltando = [d for d in datas if pd.Timestamp(d) not in self.calendario_completo.index]
        if faltando:
            raise KeyError(f"calendário não cobre {faltando[0]:%Y-%m-%d}")
        return (self.calendario_completo.loc[[pd.Timestamp(d) for d in datas], colunas]
                .astype(float).to_numpy())

    def indice_da_data(self, grupo, prioridade, data):
        """Posição de `data` na série completa do grupo, ou None se a data não existe."""
        s = self.serie(grupo, prioridade)
        achados = s.index[s.data == pd.Timestamp(data)]
        return int(achados[0]) if len(achados) else None

    def linha_manifesto(self, grupo, prioridade, horizonte):
        m = self.manifesto
        sel = m[(m.tipo_tratamento == grupo) & (m.prioridade == prioridade)
                & (m.horizonte == horizonte)]
        if sel.empty:
            raise KeyError(f"sem modelo para {grupo} P{prioridade} {horizonte}")
        return sel.iloc[0]


# ==================================================================================================
# Montagem das séries
# ==================================================================================================

def _calendario_janela(calendario, passos=cfg.PASSO_MAXIMO):
    """Agregados de calendário de duas janelas de 7 dias, ambos conhecidos em D.

    - `_7d`  — janela retroativa D-6..D. É a exógena da série agregada: `soma7(D)` cobre
      exatamente esses dias.
    - `_j7`  — janela futura D+1..D+7. Mostrada na tela como o calendário do período previsto.

    A soma é escrita como soma explícita de `shift` — sete termos, sem como estar deslocada
    sem que se veja.
    """
    c = calendario.sort_values("data").reset_index(drop=True)
    janela = pd.DataFrame({"data": c.data})
    for coluna, nome in cfg.JANELAS_CALENDARIO:
        s = c[coluna].astype(float)
        janela[f"{nome}_7d"] = sum(s.shift(k) for k in range(0, passos))
        janela[f"{nome}_j7"] = sum(s.shift(-k) for k in range(1, passos + 1))
    return janela


def _agregar_total(fato):
    """Acrescenta o grupo `total` — soma das duas fatias, razões reconstruídas dos componentes.

    Somar duas razões não significa nada: dois valores de 0,8 incidente por IC não somam 1,6.
    Por isso `inc_por_*` do total sai de numerador e denominador somados antes de dividir.
    """
    diretas = [c for c in cfg.FEATURES_EXOGENAS if c not in cfg.COMPONENTES_RAZAO]
    somaveis = ["abertos"] + diretas + ["fechados_kpi_violado"]
    somaveis = [c for c in dict.fromkeys(somaveis) if c in fato.columns]

    total = fato.groupby(["data", "prioridade"], as_index=False)[somaveis].sum()
    for razao, (num, den) in cfg.COMPONENTES_RAZAO.items():
        total[razao] = total[num] / total[den].where(total[den] > 0)
    # Duração é mediana, não soma: no total fica a média ponderada por volume das duas fatias.
    peso = fato.assign(_peso=fato.abertos.clip(lower=0))
    for col in ("duracao_mediana_h", "duracao_p90_h"):
        if col in fato.columns:
            num = (peso[col].fillna(0) * peso._peso).groupby(
                [peso.data, peso.prioridade]).sum()
            den = peso._peso.where(peso[col].notna(), 0).groupby(
                [peso.data, peso.prioridade]).sum()
            media = (num / den.where(den > 0)).rename(col).reset_index()
            total = total.merge(media, on=["data", "prioridade"], how="left")
    total["tipo_tratamento"] = "total"

    colunas = (["data", "prioridade", "tipo_tratamento", "abertos"]
               + cfg.FEATURES_EXOGENAS
               + [c for c in cfg.FEATURES_CONTEXTO if c in fato.columns]
               + ["fechados_kpi_violado"])
    colunas = [c for c in dict.fromkeys(colunas) if c in fato.columns or c in total.columns]
    for c in colunas:
        if c not in total.columns:
            total[c] = np.nan
    return pd.concat([fato[colunas], total[colunas]], ignore_index=True)


def _montar_series(fato, calendario, calendario_janela):
    """{(grupo, prioridade): DataFrame diário do histórico INTEIRO, com marca da janela}.

    Diferença deliberada em relação ao notebook: a série guardada não é recortada na janela do
    grupo — o recorte vira a coluna `na_janela` e o atributo `idx_janela`. Isso permite responder
    sobre uma data anterior à janela (selo `FORA DA JANELA`) sem montar uma segunda estrutura.
    Para tudo que é treino/teste, o que se usa é a fatia `idx_janela:`, idêntica ao notebook.
    """
    base = _agregar_total(fato)
    cal = calendario[["data"] + cfg.FEATURES_CALENDARIO]

    series = {}
    for grupo in cfg.GRUPOS:
        inicio = pd.Timestamp(cfg.JANELA[grupo]["inicio"])
        fim = pd.Timestamp(cfg.JANELA[grupo]["fim"])
        for p in cfg.PRIORIDADES:
            s = (base[(base.tipo_tratamento == grupo) & (base.prioridade == p)]
                 .sort_values("data").reset_index(drop=True))

            # Sobre o histórico inteiro, antes de qualquer recorte (§4.1 do contrato).
            s["soma7"] = s.abertos.rolling(cfg.PASSO_MAXIMO,
                                           min_periods=cfg.PASSO_MAXIMO).sum()
            s["y_acum_1a7"] = s.soma7.shift(-cfg.PASSO_MAXIMO)

            s = s[s.data <= fim]
            s = (s.drop(columns=["prioridade", "tipo_tratamento"])
                 .merge(cal, on="data", how="left")
                 .merge(calendario_janela, on="data", how="left")
                 .sort_values("data").reset_index(drop=True))
            s["na_janela"] = s.data >= inicio

            assert s.data.is_unique, f"{grupo} P{p}: data duplicada"
            assert (s.data.diff().dropna() == pd.Timedelta(days=1)).all(), \
                f"{grupo} P{p}: grade de datas com buraco"

            s.attrs["grupo"] = grupo
            s.attrs["prioridade"] = p
            s.attrs["idx_janela"] = int(s.index[s.na_janela][0])
            series[(grupo, p)] = s
    return series


# ==================================================================================================
# Classificação da data
# ==================================================================================================

def classificar(dominio, grupo, prioridade, data, horizonte):
    """Em que situação a data de origem `D` está, para este grupo e este horizonte.

    Devolve sempre um dicionário com o selo, a explicação de negócio, os índices de origem e de
    alvo, e as duas perguntas que a tela precisa responder: dá para prever, e existe real.
    Ver a tabela de selos em `docs/CONTRATO_MODELOS.md` §6 e no plano §2.
    """
    data = pd.Timestamp(data)
    passos = cfg.HORIZONTES[horizonte]
    s = dominio.serie(grupo, prioridade)
    corte = pd.Timestamp(cfg.JANELA[grupo]["corte"])
    inicio = pd.Timestamp(cfg.JANELA[grupo]["inicio"])

    i = dominio.indice_da_data(grupo, prioridade, data)
    if i is None:
        return _selo(
            cfg.SELO_SEM_FEATURES,
            f"{data:%d/%m/%Y} está fora do histórico disponível "
            f"({dominio.data_min:%d/%m/%Y} a {dominio.data_max:%d/%m/%Y}). "
            "Sem features, não há o que servir ao modelo.",
            prever=False, tem_real=False,
        )

    idx_janela = s.attrs["idx_janela"]
    tem_alvo = i + passos < len(s)
    data_alvo = s.data.iloc[i + passos] if tem_alvo else data + pd.Timedelta(days=passos)

    if i < idx_janela:
        return _selo(
            cfg.SELO_FORA_DA_JANELA,
            _texto_fora_da_janela(grupo, data, inicio),
            prever=True, tem_real=tem_alvo, i=i, i_alvo=i + passos if tem_alvo else None,
            data_alvo=data_alvo, extrapolacao=True,
        )

    if not tem_alvo:
        return _selo(
            cfg.SELO_SEM_RESPOSTA,
            f"As features de {data:%d/%m/%Y} existem e o modelo responde, mas o alvo cairia em "
            f"{data_alvo:%d/%m/%Y}, depois do fim da série ({dominio.data_max:%d/%m/%Y}). "
            "Previsão sem resposta real para comparar — é o caso de uso em produção.",
            prever=True, tem_real=False, i=i, i_alvo=None, data_alvo=data_alvo,
        )

    if s.data.iloc[i + 1] >= corte:
        return _selo(
            cfg.SELO_TESTE,
            f"Origem dentro do período de teste (a partir de {corte:%d/%m/%Y}). O modelo nunca "
            "viu este alvo no ajuste: é leitura out-of-sample, e é ela que aparece em "
            "`g_previsoes.csv`.",
            prever=True, tem_real=True, i=i, i_alvo=i + passos, data_alvo=data_alvo,
        )

    if s.data.iloc[i + passos] >= corte:
        return _selo(
            cfg.SELO_EMBARGO,
            f"Origem no embargo (*purged split*): a janela-alvo vai até {data_alvo:%d/%m/%Y} e "
            f"invade o teste, que começa em {corte:%d/%m/%Y}. Esta origem não foi amostra de "
            "treino nem ponto de teste — foi descartada das duas leituras.",
            prever=True, tem_real=True, i=i, i_alvo=i + passos, data_alvo=data_alvo,
        )

    return _selo(
        cfg.SELO_TREINO,
        f"Origem dentro do período de treino ({inicio:%d/%m/%Y} a "
        f"{corte - pd.Timedelta(days=1):%d/%m/%Y}). A previsão é in-sample: este alvo participou "
        "do ajuste dos parâmetros, então a acurácia aqui é otimista por construção.",
        prever=True, tem_real=True, i=i, i_alvo=i + passos, data_alvo=data_alvo,
    )


def _texto_fora_da_janela(grupo, data, inicio):
    base = (f"{data:%d/%m/%Y} tem features, mas é anterior ao início da janela de {grupo} "
            f"({inicio:%d/%m/%Y}). A previsão é extrapolação: o modelo nunca foi ajustado nem "
            "avaliado neste período.")
    if data < pd.Timestamp(cfg.INICIO_R2):
        return base + (" Pior: a data está no regime R1, que é artefato da extração e foi "
                       "descartado da modelagem inteira. O número não deve ser usado.")
    if grupo in ("sem_intervencao", "total") and data < pd.Timestamp(cfg.INICIO_R3):
        return base + (f" A data está antes de {pd.Timestamp(cfg.INICIO_R3):%d/%m/%Y}, quando "
                       "entrou o pipeline de monitoramento automático — a quebra estrutural que "
                       "define este grupo. Antes dela a série tem outro patamar.")
    return base


def _selo(selo, explicacao, prever, tem_real, i=None, i_alvo=None, data_alvo=None,
          extrapolacao=False):
    return {
        "selo": selo,
        "explicacao": explicacao,
        "pode_prever": prever,
        "tem_real": tem_real,
        "extrapolacao": extrapolacao,
        "indice_origem": i,
        "indice_alvo": i_alvo,
        "data_alvo": data_alvo.date().isoformat() if data_alvo is not None else None,
    }


# ==================================================================================================
# Features do dia
# ==================================================================================================

def features_do_dia(dominio, grupo, prioridade, data, horizonte):
    """As entradas que o modelo e a tela veem naquele dia, agrupadas por origem."""
    i = dominio.indice_da_data(grupo, prioridade, data)
    if i is None:
        return None
    s = dominio.serie(grupo, prioridade)
    linha = s.iloc[i]

    def bloco(colunas):
        return {c: _limpo(linha[c]) for c in colunas if c in s.columns}

    exog = cfg.EXOG_MODELO[horizonte]
    return {
        "serie": {"abertos": _limpo(linha["abertos"]), "soma7": _limpo(linha["soma7"])},
        "calendario": bloco(cfg.FEATURES_CALENDARIO),
        "janela": bloco(cfg.FEATURES_JANELA),
        "exogenas": bloco(cfg.FEATURES_EXOGENAS),
        "contexto": bloco(cfg.FEATURES_CONTEXTO),
        "exogenas_do_modelo": {c: _limpo(linha[c]) for c in exog if c in s.columns},
    }


def _limpo(valor):
    """Converte para tipo serializável em JSON; NaN vira None."""
    if valor is None:
        return None
    if isinstance(valor, (np.bool_, bool)):
        return bool(valor)
    if isinstance(valor, pd.Timestamp):
        return valor.date().isoformat()
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if not np.isfinite(f):
        return None
    return round(f, 6)


# ==================================================================================================
# Instância única
# ==================================================================================================

@lru_cache(maxsize=1)
def obter_dominio():
    return Dominio()
