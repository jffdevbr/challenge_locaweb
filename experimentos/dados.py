"""Monta as 9 séries exatamente como o notebook de treino, mas fora dele.

Réplica fiel das células 5, 8, 10 e 12 de `notebooks/model_training.ipynb`. A fidelidade não é
capricho: se a série montada aqui não for bit a bit a mesma, nenhuma comparação com a safra
atual vale nada. O teste de sanidade de `protocolo.py` cobra isso.

Diferença deliberada em relação ao notebook: aqui o calendário é mesclado inteiro (menos as
colunas de texto), porque a onda C precisa de `num_dia_util` e `mes`, que a lista original não
carregava. Nenhuma coluna nova é criada — todas já existem na silver.
"""
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_SILVER = RAIZ / "2_silver_data"

PRIORIDADES = [2, 3, 4]
GRUPOS = ["com_intervencao", "sem_intervencao", "total"]

JANELA = {
    "com_intervencao": {"inicio": "2025-01-01", "fim": "2025-12-31", "dias_teste": 42},
    "sem_intervencao": {"inicio": "2025-09-01", "fim": "2025-12-31", "dias_teste": 28},
    "total":           {"inicio": "2025-09-01", "fim": "2025-12-31", "dias_teste": 28},
}

HORIZONTES = {"D+1": 1, "D+7": 7}
COLUNA_SERIE = {"D+1": "abertos", "D+7": "soma7"}
PASSO_MAXIMO = HORIZONTES["D+7"]
PERIODO_SAZONAL = 7
EMBARGO = {h: passos - 1 for h, passos in HORIZONTES.items()}

# Exógenas medidas em D. Mesma lista pré-registrada da célula 5 do notebook.
FEATURES_EXOGENAS_MODELO = [
    "inc_por_ic", "inc_por_descricao", "inc_por_time",
    "fechados", "backlog", "saldo_aberto_fechado",
    "abertos_sem_classificacao",
    "ics_distintos", "times_distintos", "descricoes_distintas",
]

COMPONENTES_RAZAO = {
    "inc_por_ic": ("abertos", "ics_distintos"),
    "inc_por_descricao": ("abertos", "descricoes_distintas"),
    "inc_por_time": ("abertos", "times_distintos"),
}

JANELAS_CALENDARIO = [("feriado", "feriados"), ("dia_util", "dias_uteis"),
                      ("vespera_feriado", "vesperas")]

# Colunas de calendário mescladas na série. Só numéricas — as de texto (`nome_feriado`,
# `tipo_dia`, ...) não entram em modelo nenhum.
COLUNAS_CALENDARIO = [
    "dia_semana", "fim_de_semana", "dia_util", "feriado",
    "vespera_feriado", "pos_feriado", "dia_mes", "mes", "num_dia_util",
    "sen_semana", "cos_semana", "sen_ano", "cos_ano",
]


def carregar_brutos():
    fato = pd.read_csv(CAMINHO_SILVER / "s_fato_diario_prioridade.csv",
                       sep=";", parse_dates=["data"])
    calendario = pd.read_csv(CAMINHO_SILVER / "s_dim_calendario.csv",
                             sep=";", parse_dates=["data"])
    return fato, calendario


def agregar_total(fato):
    """Acrescenta o grupo `total`, somando componentes ANTES de dividir as razões (célula 8)."""
    componentes = ["abertos"] + [c for c in FEATURES_EXOGENAS_MODELO if c not in COMPONENTES_RAZAO]
    total = fato.groupby(["data", "prioridade"], as_index=False)[componentes].sum()
    for razao, (num, den) in COMPONENTES_RAZAO.items():
        total[razao] = total[num] / total[den].where(total[den] > 0)
    total["tipo_tratamento"] = "total"

    colunas = ["data", "prioridade", "tipo_tratamento", "abertos"] + FEATURES_EXOGENAS_MODELO
    return pd.concat([fato[colunas], total[colunas]], ignore_index=True)


def calendario_janela(cal, passos=PASSO_MAXIMO):
    """Agregados de calendário das janelas retroativa (`_7d`) e futura (`_j7`) — célula 8."""
    c = cal.sort_values("data").reset_index(drop=True)
    janela = pd.DataFrame({"data": c.data})
    for coluna, nome in JANELAS_CALENDARIO:
        s = c[coluna].astype(float)
        janela[f"{nome}_7d"] = sum(s.shift(k) for k in range(0, passos))
        janela[f"{nome}_j7"] = sum(s.shift(-k) for k in range(1, passos + 1))
    meio = passos // 2 + 1
    janela["sen_ano_j7"] = c.sen_ano.shift(-meio)
    janela["cos_ano_j7"] = c.cos_ano.shift(-meio)
    return janela


def montar_series(fato, calendario):
    """{(grupo, prioridade): DataFrame diário} com os dois alvos e todas as features (célula 10)."""
    base = agregar_total(fato)
    cal = calendario[["data"] + COLUNAS_CALENDARIO]
    cal_j7 = calendario_janela(calendario)

    series = {}
    for grupo in GRUPOS:
        ini, fim = JANELA[grupo]["inicio"], JANELA[grupo]["fim"]
        for p in PRIORIDADES:
            s = (base[(base.tipo_tratamento == grupo) & (base.prioridade == p)]
                 .sort_values("data").reset_index(drop=True))

            # No histórico inteiro, ANTES do recorte — a ordem importa.
            s["soma7"] = s.abertos.rolling(PASSO_MAXIMO, min_periods=PASSO_MAXIMO).sum()
            s["y_acum_1a7"] = s.soma7.shift(-PASSO_MAXIMO)

            s = s[(s.data >= ini) & (s.data <= fim)]
            s = (s.drop(columns=["prioridade", "tipo_tratamento"])
                 .merge(cal, on="data", how="left")
                 .merge(cal_j7, on="data", how="left")
                 .sort_values("data").reset_index(drop=True))

            assert s.data.is_unique, f"{grupo} P{p}: data duplicada"
            assert (s.data.diff().dropna() == pd.Timedelta(days=1)).all(), \
                f"{grupo} P{p}: grade de datas com buraco"
            assert s.soma7.notna().all(), f"{grupo} P{p}: soma7 nula dentro da janela"
            series[(grupo, p)] = s
    return series


# Exógenas observadas em D, replicadas com defasagem para cada horizonte. A defasagem é o que as
# torna admissíveis: o SARIMAX pede a exógena em cada passo previsto (linhas D+1..D+h), e a coluna
# `<c>_obs<h>` na linha D+k carrega o valor de `c` em D+k-h, que nunca é posterior a D. Sem essa
# defasagem, usar `backlog` para prever D+1 seria ler o backlog do próprio dia previsto — o modelo
# ficaria ótimo no papel e impossível de servir.
FEATURES_OBSERVADAS = FEATURES_EXOGENAS_MODELO + ["soma7"]


def _acrescentar_defasadas(series):
    """Cria `<c>_obs<h>` = `c` defasada de h dias.

    As h primeiras linhas ficariam nulas pelo `shift`; são preenchidas de trás para frente porque
    caem no começo da janela de ajuste, longe de qualquer origem avaliada. Sem esse preenchimento
    a coluna inteira seria descartada por conter nulo — que foi exatamente o que aconteceu na
    primeira execução da onda C, deixando de fora todo o bloco de exógenas observadas.
    """
    for s in series.values():
        for c in FEATURES_OBSERVADAS:
            for h in sorted(set(HORIZONTES.values())):
                s[f"{c}_obs{h}"] = s[c].shift(h).bfill()
    return series


def definir_corte(grupo):
    fim = pd.Timestamp(JANELA[grupo]["fim"])
    return fim - pd.Timedelta(days=JANELA[grupo]["dias_teste"] - 1)


CORTE = {g: definir_corte(g) for g in GRUPOS}

_fato, _calendario = carregar_brutos()
SERIES = _acrescentar_defasadas(montar_series(_fato, _calendario))
N_TREINO = {chave: int((s.data < CORTE[chave[0]]).sum()) for chave, s in SERIES.items()}


def forca_sazonal_semanal(grupo, prioridade, horizonte):
    """η² do dia-da-semana sobre a série alvo, medido SÓ NO TREINO.

    É o que decide se vale gastar orçamento testando bloco sazonal naquela série. Medir no treino
    e não na série inteira não é detalhe: medir no teste seria escolher a estrutura do modelo
    olhando a resposta.
    """
    s = SERIES[(grupo, prioridade)]
    n = N_TREINO[(grupo, prioridade)]
    y = s[COLUNA_SERIE[horizonte]].iloc[:n].astype(float)
    dow = s.dia_semana.iloc[:n]
    total = float(((y - y.mean()) ** 2).sum())
    if total <= 0:
        return 0.0
    entre = float(sum(len(g) * (g.mean() - y.mean()) ** 2 for _, g in y.groupby(dow)))
    return entre / total


def matriz_exog(grupo, prioridade, colunas):
    """Matriz de exógenas alinhada à série, com nulos preenchidos por 0 (célula 66 faz o mesmo)."""
    if not colunas:
        return None
    s = SERIES[(grupo, prioridade)]
    x = s[list(colunas)].astype(float).to_numpy()
    return np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)


def serie_alvo(grupo, prioridade, horizonte):
    return SERIES[(grupo, prioridade)][COLUNA_SERIE[horizonte]].astype(float).to_numpy()
