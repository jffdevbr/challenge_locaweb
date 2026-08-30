"""Carga dos 18 artefatos e produção da previsão.

Reproduz `previsoes_statsmodels()` do notebook (§7.2) com uma diferença de forma, não de conteúdo:
em vez de remontar o `SARIMAX(...).filter(params)` a partir da especificação, usa `res.apply()`
sobre o resultado carregado — mesma operação, com os parâmetros já congelados dentro do artefato.

A previsão é o **último** passo da projeção. Os passos intermediários existem só porque o filtro
precisa deles; nenhum vira previsão e nenhum realimenta nada.
"""

import warnings
from functools import lru_cache

import numpy as np
import pandas as pd
import statsmodels.api as sm

from api import config as cfg
from api import dominio as dom


class Modelos:
    """Os 18 artefatos, carregados uma vez e indexados por (grupo, prioridade, horizonte)."""

    def __init__(self, dominio):
        self.artefatos = {}
        self.metadados = {}
        for _, linha in dominio.manifesto.iterrows():
            chave = (linha.tipo_tratamento, int(linha.prioridade), linha.horizonte)
            caminho = cfg.CAMINHO_MODELOS / linha.arquivo
            if not caminho.exists():
                raise FileNotFoundError(f"artefato do manifesto ausente: {caminho}")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = sm.load(str(caminho))

            # O .pkl não guarda o nome das colunas exógenas (foi ajustado com ndarray). A
            # conferência possível é a contagem, e ela é feita na CARGA: um descasamento aqui é
            # erro de configuração, e erro de configuração tem de derrubar o startup, não a
            # requisição.
            esperado = cfg.EXOG_MODELO[linha.horizonte] if linha.modelo == "SARIMA" else []
            if int(res.model.k_exog) != len(esperado):
                raise ValueError(
                    f"{linha.arquivo}: o artefato tem k_exog={res.model.k_exog}, mas a "
                    f"configuração de {linha.modelo} {linha.horizonte} prevê {len(esperado)} "
                    f"({esperado or 'nenhuma'})"
                )

            self.artefatos[chave] = res
            self.metadados[chave] = {
                "arquivo": linha.arquivo,
                "modelo": linha.modelo,
                "serie_modelada": linha.serie_modelada,
                "passos": int(linha.passos),
                "exogenas": esperado,
                "order": tuple(int(x) for x in res.model.order),
                "seasonal_order": tuple(int(x) for x in res.model.seasonal_order),
                "ajustado_ate": str(linha.ajustado_ate),
                "n_treino": int(linha.n_treino),
                "mae": float(linha.mae),
                "mase": float(linha.mase),
                "mae_ingenuo": float(linha.mae_ingenuo),
                "ganho_vs_ingenuo": float(linha.ganho_vs_ingenuo),
                "supera_ingenuo": bool(linha.supera_ingenuo),
                "regra_ingenua": linha.regra_ingenua,
                "configuracao": linha.configuracao,
            }

    def __len__(self):
        return len(self.artefatos)

    def meta(self, grupo, prioridade, horizonte):
        return self.metadados[(grupo, int(prioridade), horizonte)]

    def artefato(self, grupo, prioridade, horizonte):
        return self.artefatos[(grupo, int(prioridade), horizonte)]


# ==================================================================================================
# Previsão
# ==================================================================================================

def prever(dominio, modelos, grupo, prioridade, horizonte, data, alfa=cfg.ALFA_BANDA_TELA):
    """Previsão do horizonte a partir da origem `data`, com banda e leitura do real.

    Devolve `None` se a data não tem features. Fora isso devolve sempre um dicionário completo —
    inclusive nos casos em que a previsão é extrapolação, porque esconder o número e mostrar só o
    aviso deixaria a tela sem o que comparar.
    """
    situacao = dom.classificar(dominio, grupo, prioridade, data, horizonte)
    if not situacao["pode_prever"]:
        return {"grupo": grupo, "situacao": situacao, "previsao": None}

    s = dominio.serie(grupo, prioridade)
    passos = cfg.HORIZONTES[horizonte]
    meta = modelos.meta(grupo, prioridade, horizonte)
    i = situacao["indice_origem"]

    # Fatia de histórico: da janela do grupo até a origem. Fora da janela, tudo que existe — e o
    # selo já avisou que ali é extrapolação.
    inicio = 0 if situacao["selo"] == cfg.SELO_FORA_DA_JANELA else s.attrs["idx_janela"]
    historico = s[cfg.COLUNA_SERIE[horizonte]].iloc[inicio:i + 1].astype(float).to_numpy()

    exog_hist = exog_fut = None
    if meta["exogenas"]:
        exog_hist = s[meta["exogenas"]].iloc[inicio:i + 1].astype(float).to_numpy()
        datas_futuras = [s.data.iloc[i] + pd.Timedelta(days=k) for k in range(1, passos + 1)]
        exog_fut = dominio.calendario_em(datas_futuras, meta["exogenas"])

    ponto, banda, fallback = _projetar(modelos.artefato(grupo, prioridade, horizonte),
                                       historico, exog_hist, exog_fut, passos, alfa)

    real = None
    if situacao["tem_real"]:
        real = float(s[cfg.COLUNA_SERIE[horizonte]].iloc[situacao["indice_alvo"]])

    return {
        "grupo": grupo,
        "situacao": situacao,
        "modelo": meta["modelo"],
        "configuracao": meta["configuracao"],
        "serie_modelada": meta["serie_modelada"],
        "previsao": round(ponto, 2),
        "banda": {"inferior": round(banda[0], 2), "superior": round(banda[1], 2),
                  "confianca_pct": round((1 - alfa) * 100)},
        "real": real,
        "erro": round(ponto - real, 2) if real is not None else None,
        "acuracia_pct": acuracia(ponto, real),
        "ingenuo": _ingenuo(s, i, horizonte, meta["regra_ingenua"]),
        "desempenho_no_teste": {
            "mae": meta["mae"], "mase": meta["mase"], "mae_ingenuo": meta["mae_ingenuo"],
            "ganho_vs_ingenuo": meta["ganho_vs_ingenuo"],
            "supera_ingenuo": meta["supera_ingenuo"], "regra_ingenua": meta["regra_ingenua"],
        },
        "usou_fallback": fallback,
    }


def _projetar(res, historico, exog_hist, exog_fut, passos, alfa):
    """Refiltra o estado com o dado real e projeta. Fallback: o último valor observado."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ajuste = res.apply(historico, exog=exog_hist, refit=False)
            proj = ajuste.get_forecast(steps=passos, exog=exog_fut)
            caminho = np.asarray(proj.predicted_mean, dtype=float)
            limites = np.asarray(proj.conf_int(alpha=alfa), dtype=float)
        valor = float(caminho[-1])
        inferior, superior = float(limites[-1, 0]), float(limites[-1, 1])
        if not np.isfinite(valor):
            raise ValueError("projeção não finita")
    except Exception:
        valor = float(historico[-1])
        inferior = superior = valor
        return max(valor, 0.0), (max(inferior, 0.0), max(superior, 0.0)), True

    if not np.isfinite(inferior) or not np.isfinite(superior):
        inferior = superior = valor
    return max(valor, 0.0), (max(inferior, 0.0), max(superior, 0.0)), False


def _ingenuo(s, i, horizonte, regra):
    """O piso de referência aplicado nesta origem, na regra que venceu dentro do treino.

    Nas linhas gerais o manifesto pode trazer mais de uma regra separada por vírgula (as três
    prioridades divergiram); aqui o grão já é a prioridade, então é uma só.
    """
    regra = str(regra).split(",")[0].strip()
    if horizonte == "D+1":
        valor = float(s.abertos.iloc[i])
    elif regra == "7 x abertos[D]":
        valor = float(cfg.PASSO_MAXIMO * s.abertos.iloc[i])
    else:
        valor = float(s.soma7.iloc[i])
    return {"regra": regra, "valor": round(max(valor, 0.0), 2)}


def acuracia(previsto, real):
    """Quão perto a previsão chegou do real, em %.

    Piso 1 no denominador, mesma convenção de `metricas()` no notebook — a série tem dias de
    valor 0, e sem o piso a divisão explodiria justamente onde o erro absoluto é pequeno.
    """
    if real is None or previsto is None:
        return None
    return round(max(0.0, 1 - abs(previsto - real) / max(abs(real), 1.0)) * 100, 1)


@lru_cache(maxsize=1)
def obter_modelos():
    return Modelos(dom.obter_dominio())
