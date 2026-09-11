"""Carga dos 18 artefatos e produção da previsão.

Três famílias, cada uma com o seu caminho de carga (ver `docs/CONTRATO_MODELOS.md` §1 e §7):

- `SARIMAX` — `.pkl` com os parâmetros congelados no treino, mais o sidecar `.config.json`.
  Serve com `res.apply(historico, refit=False)`: o estado do filtro avança com o dado real, os
  parâmetros não se movem. É o `SARIMAX(...).filter(params)` do notebook, com o modelo já montado.
- `ETS` — `.json` com a especificação e os parâmetros. `ETSModel(historico).smooth(params)`
  reconstrói o estado sem reajustar — o equivalente do `refit=False`.
- `Theta` — `.json` só com a configuração. O método é fechado e reajusta a cada chamada.

O que não está no artefato e muda o número sem levantar erro: a transformação da série (`log1p`
antes, `expm1` depois), a padronização das exógenas (`(x - centro) / escala`) e a trava de
sanidade do treino. As três ficam aqui, comuns às famílias.

A previsão é o **último** passo da projeção. Os passos intermediários existem só porque o filtro
precisa deles; nenhum vira previsão e nenhum realimenta nada.
"""

import json
import re
import warnings
from functools import lru_cache

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.forecasting.theta import ThetaModel

from api import config as cfg
from api import dominio as dom

_DEFASADA = re.compile(r"(.+)_obs(\d+)")


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
            if linha.familia not in cfg.FAMILIAS:
                raise ValueError(f"{linha.arquivo}: família {linha.familia!r} sem caminho de "
                                 f"serving (servidas: {cfg.FAMILIAS})")

            if linha.familia == "SARIMAX":
                sidecar = caminho.with_suffix(".config.json")
                if not sidecar.exists():
                    raise FileNotFoundError(f"sidecar ausente: {sidecar} — sem ele não há "
                                            "transformação nem padronização das exógenas")
                config = json.loads(sidecar.read_text(encoding="utf-8"))
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    artefato = sm.load(str(caminho))
                # O .pkl não guarda o nome das colunas exógenas (foi ajustado com ndarray). A
                # conferência possível é a contagem, e ela é feita na CARGA: um descasamento aqui
                # é erro de configuração, e erro de configuração tem de derrubar o startup, não a
                # requisição.
                if int(artefato.model.k_exog) != len(config["exog"]):
                    raise ValueError(f"{linha.arquivo}: k_exog={artefato.model.k_exog}, mas o "
                                     f"sidecar lista {len(config['exog'])} exógenas")
            else:
                config = json.loads(caminho.read_text(encoding="utf-8"))
                artefato = config

            if config["transformacao"] != linha.transformacao:
                raise ValueError(f"{linha.arquivo}: o manifesto diz transformação "
                                 f"{linha.transformacao!r}, o artefato diz "
                                 f"{config['transformacao']!r}")
            exog = list(config.get("exog") or [])
            _conferir_defasagens(linha.arquivo, exog, cfg.HORIZONTES[linha.horizonte])

            self.artefatos[chave] = artefato
            self.metadados[chave] = {
                "arquivo": linha.arquivo,
                "modelo": linha.modelo,
                "familia": linha.familia,
                "serie_modelada": linha.serie_modelada,
                "passos": int(linha.passos),
                "transformacao": config["transformacao"],
                "exog": exog,
                "exog_centro": np.asarray(config.get("exog_centro") or [], dtype=float),
                "exog_escala": np.asarray(config.get("exog_escala") or [], dtype=float),
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


def _conferir_defasagens(arquivo, exog, passos):
    """Uma exógena `_obs<h>` só é servível se `h >= passos`: a linha D+passos lê D+passos-h."""
    for c in exog:
        m = _DEFASADA.fullmatch(c)
        if m and int(m.group(2)) < passos:
            raise ValueError(f"{arquivo}: {c} tem defasagem {m.group(2)} < {passos} passos — "
                             "a exógena futura seria posterior à origem")


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
    exog_hist, exog_fut = _exogenas(dominio, s, inicio, i, passos, meta)

    ponto, banda, fallback = _projetar(meta, modelos.artefato(grupo, prioridade, horizonte),
                                       historico, exog_hist, exog_fut, passos, alfa)

    real = None
    if situacao["tem_real"]:
        real = float(s[cfg.COLUNA_SERIE[horizonte]].iloc[situacao["indice_alvo"]])

    return {
        "grupo": grupo,
        "situacao": situacao,
        "modelo": meta["modelo"],
        "familia": meta["familia"],
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


def _exogenas(dominio, s, inicio, i, passos, meta):
    """Matriz histórica (`inicio..i`) e futura (`D+1..D+passos`), já padronizadas.

    Futuro de calendário vem da dimensão de calendário, que vai até 2026-12-31 — inclusive além
    do fim da série. Futuro de `<c>_obs<h>` é o valor de `c` em `D+k-h`, que a carga já garantiu
    não ser posterior à origem. Mesma ordem do notebook: `nan_to_num` no bruto, depois
    `(x - centro) / escala` com a escala da janela de treino, gravada no sidecar.
    """
    colunas = meta["exog"]
    if not colunas:
        return None, None

    hist = s[colunas].iloc[inicio:i + 1].astype(float).to_numpy()
    datas = [s.data.iloc[i] + pd.Timedelta(days=k) for k in range(1, passos + 1)]
    fut = np.empty((passos, len(colunas)))
    for j, c in enumerate(colunas):
        m = _DEFASADA.fullmatch(c)
        if m is None:
            fut[:, j] = dominio.calendario_em(datas, [c])[:, 0]
        else:
            base, h = m.group(1), int(m.group(2))
            fut[:, j] = [float(s[base].iloc[i + k - h]) for k in range(1, passos + 1)]

    def padronizar(x):
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        return (x - meta["exog_centro"]) / meta["exog_escala"]

    return padronizar(hist), padronizar(fut)


def _projetar(meta, artefato, historico, exog_hist, exog_fut, passos, alfa):
    """Projeta pela família, desfaz a transformação e aplica a trava. Fallback: último valor."""
    transformacao = meta["transformacao"]
    y_t = _aplicar(historico, transformacao)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ponto, inferior, superior = _PROJETORES[meta["familia"]](
                artefato, y_t, exog_hist, exog_fut, passos, alfa)
        if not np.isfinite(ponto):
            raise ValueError("projeção não finita")
    except Exception:
        valor = max(float(historico[-1]), 0.0)
        return valor, (valor, valor), True

    ponto, inferior, superior = (_desfazer(v, transformacao) for v in (ponto, inferior, superior))

    # A mesma trava do treino (`protocolo.avaliar`): contém raiz explosiva e extrapolação absurda
    # usando só o histórico até a origem.
    teto = 2.0 * float(np.max(historico[-cfg.TETO_JANELA_DIAS:])) + 10.0
    ponto = float(np.clip(ponto, 0.0, teto))
    if not (np.isfinite(inferior) and np.isfinite(superior)):
        inferior = superior = ponto
    inferior = float(np.clip(inferior, 0.0, ponto))
    superior = float(np.clip(superior, ponto, teto))
    return ponto, (inferior, superior), False


def _sarimax(res, y_t, exog_hist, exog_fut, passos, alfa):
    proj = res.apply(y_t, exog=exog_hist, refit=False).get_forecast(steps=passos, exog=exog_fut)
    media = np.asarray(proj.predicted_mean, dtype=float)
    limites = np.asarray(proj.conf_int(alpha=alfa), dtype=float)
    return float(media[-1]), float(limites[-1, 0]), float(limites[-1, 1])


def _ets(config, y_t, _exog_hist, _exog_fut, passos, alfa):
    # `pd.Series`, não ndarray: no statsmodels 0.14.6 o `get_prediction` do ETS quebra com
    # ndarray (procura `.index` no resultado). O ponto é idêntico nos dois casos.
    modelo = ETSModel(pd.Series(y_t), error=config["error"], trend=config["trend"],
                      damped_trend=config["damped_trend"], seasonal=config["seasonal"],
                      seasonal_periods=config["seasonal_periods"])
    res = modelo.smooth(config["params"])
    ponto = float(np.asarray(res.forecast(steps=passos), dtype=float)[-1])
    quadro = res.get_prediction(start=len(y_t), end=len(y_t) + passos - 1) \
                .summary_frame(alpha=alfa)
    return ponto, float(quadro["pi_lower"].iloc[-1]), float(quadro["pi_upper"].iloc[-1])


def _theta(config, y_t, _exog_hist, _exog_fut, passos, alfa):
    res = ThetaModel(y_t, period=config["period"], deseasonalize=config["deseasonalize"],
                     use_test=False).fit()
    ponto = float(np.asarray(res.forecast(steps=passos), dtype=float)[-1])
    limites = res.prediction_intervals(steps=passos, alpha=alfa)
    return ponto, float(limites["lower"].iloc[-1]), float(limites["upper"].iloc[-1])


_PROJETORES = {"SARIMAX": _sarimax, "ETS": _ets, "Theta": _theta}


def _aplicar(y, transformacao):
    return np.log1p(np.maximum(np.asarray(y, dtype=float), 0.0)) if transformacao == "log1p" \
        else np.asarray(y, dtype=float)


def _desfazer(v, transformacao):
    """`expm1` puro, sem correção de Jensen — a métrica é MAE, cujo previsor ótimo é a mediana."""
    with np.errstate(over="ignore"):
        return float(np.expm1(v)) if transformacao == "log1p" else float(v)


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
