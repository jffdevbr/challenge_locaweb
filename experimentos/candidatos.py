"""Os candidatos e a busca de ordem.

Cada candidato sabe duas coisas: ajustar-se numa janela e prever a partir de uma origem. Nada
mais. Isso mantém `protocolo.py` cego à família do modelo e garante que todos sejam avaliados
exatamente pela mesma régua.

Duas decisões de desenho que valem ser ditas:

1. **AICc escolhe (p,q) dentro de uma família; a CV escolhe entre famílias.** AIC é comparável
   entre ordens do mesmo modelo, na mesma escala e com o mesmo `d`. Não é comparável entre
   `d=0` e `d=1` (mudam as observações efetivas) nem entre nível e log (muda a escala da
   verossimilhança). Usar AIC para decidir `d`, como a safra atual faz via ADF, é justamente
   onde o desenho antigo quebra. Aqui `d`, `D`, a transformação e o `trend` são decididos pelo
   erro fora da amostra.

2. **`log1p` volta com `expm1` puro, sem correção de Jensen.** A métrica é MAE, cujo previsor
   ótimo é a mediana; `expm1` da média em log é aproximadamente a mediana em nível. Somar
   `sigma²/2` miraria a média e pioraria o MAE. É o caso raro em que não corrigir é o correto.
"""
import warnings

import numpy as np

from dados import COLUNA_SERIE, HORIZONTES, PERIODO_SAZONAL, SERIES, matriz_exog

warnings.filterwarnings("ignore")

from statsmodels.tsa.statespace.sarimax import SARIMAX  # noqa: E402

try:
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
except Exception:                                        # pragma: no cover
    ETSModel = None
try:
    from statsmodels.tsa.forecasting.theta import ThetaModel
except Exception:                                        # pragma: no cover
    ThetaModel = None


# --- transformações -----------------------------------------------------------------------

def aplicar(y, transformacao):
    return np.log1p(np.maximum(np.asarray(y, dtype=float), 0.0)) if transformacao == "log1p" \
        else np.asarray(y, dtype=float)


def desfazer(v, transformacao):
    return float(np.expm1(v)) if transformacao == "log1p" else float(v)


# --- SARIMAX ------------------------------------------------------------------------------

def _estavel(res, tolerancia=0.999):
    """A parte autorregressiva tem todas as raízes fora do círculo unitário?

    O notebook atual ajusta com `enforce_stationarity=False`, e isso não é um detalhe: sem a
    restrição, o otimizador pode parar num modelo com raiz explosiva. Ele ajusta bem dentro da
    amostra — a verossimilhança não pune — e depois diverge ao extrapolar. Foi o que produziu uma
    previsão de 4.163 numa série cujo máximo histórico é 660.

    Manter `enforce_stationarity=False` e filtrar depois é melhor que ligar a restrição: ligada,
    ela empurra a otimização para a fronteira e piora o ajuste dos modelos legítimos. Aqui o
    candidato instável simplesmente não entra na disputa.
    """
    raizes = getattr(res, "arroots", None)
    if raizes is None or len(raizes) == 0:
        return True
    return bool(np.min(np.abs(np.asarray(raizes))) >= tolerancia)


class Sarimax:
    """SARIMAX com transformação, ordem e exógenas fixas. É a família de todos os artefatos atuais."""

    familia = "SARIMAX"

    def __init__(self, ordem, sazonal=(0, 0, 0, 0), trend="c", transformacao="nenhuma",
                 exog=(), rotulo=None):
        self.ordem = tuple(ordem)
        self.sazonal = tuple(sazonal)
        self.trend = trend
        self.transformacao = transformacao
        self.exog = tuple(exog)
        p, d, q = self.ordem
        P, D, Q, _ = self.sazonal
        self.custo = p + q + P + Q + len(self.exog) + (1 if transformacao != "nenhuma" else 0)
        self.rotulo = rotulo or (
            f"SARIMAX{self.ordem}x{self.sazonal}|{trend}|{transformacao}|e{len(self.exog)}")

    def _montar(self, y_t, exog):
        return SARIMAX(y_t, exog=exog, order=self.ordem, seasonal_order=self.sazonal,
                       trend=self.trend, enforce_stationarity=False, enforce_invertibility=False)

    def ajustar(self, grupo, prioridade, horizonte, n_ajuste):
        y = SERIES[(grupo, prioridade)][COLUNA_SERIE[horizonte]].astype(float).to_numpy()
        y_t = aplicar(y[:n_ajuste], self.transformacao)
        x = matriz_exog(grupo, prioridade, self.exog)
        centro = escala = None
        exog_aj = None
        if x is not None:
            centro = x[:n_ajuste].mean(axis=0)
            escala = x[:n_ajuste].std(axis=0)
            escala[escala < 1e-9] = 1.0
            exog_aj = (x[:n_ajuste] - centro) / escala
        try:
            res = self._montar(y_t, exog_aj).fit(disp=False, maxiter=100)
            params = np.asarray(res.params, dtype=float)
            if not np.all(np.isfinite(params)):
                return None
            if not _estavel(res):
                return None
        except Exception:
            return None
        return {"params": params, "centro": centro, "escala": escala, "aic": float(res.aic),
                "n_ajuste": n_ajuste, "k": len(params)}

    def prever(self, estado, grupo, prioridade, horizonte, origem):
        passos = HORIZONTES[horizonte]
        y = SERIES[(grupo, prioridade)][COLUNA_SERIE[horizonte]].astype(float).to_numpy()
        y_t = aplicar(y[:origem + 1], self.transformacao)
        exog_hist = exog_fut = None
        if self.exog:
            x = matriz_exog(grupo, prioridade, self.exog)
            x = (x - estado["centro"]) / estado["escala"]
            exog_hist = x[:origem + 1]
            exog_fut = x[origem + 1: origem + 1 + passos]
            if len(exog_fut) < passos:
                return None
        caminho = self._montar(y_t, exog_hist).filter(estado["params"]) \
                      .forecast(steps=passos, exog=exog_fut)
        return desfazer(np.asarray(caminho, dtype=float)[-1], self.transformacao)


def aicc(res_aic, k, n):
    """AIC corrigido para amostra pequena. Com n de 60 a 280 e k até 12, a correção não é opcional."""
    denominador = n - k - 1
    return res_aic + (2 * k * (k + 1) / denominador if denominador > 0 else np.inf)


def buscar_ordem(grupo, prioridade, horizonte, n_ajuste, transformacao, d, trend,
                 sazonal_estrutura=(0, 0, 0), q_max=3, p_max=3, exog=()):
    """Melhor (p,q) da família por AICc, ajustado na janela de ajuste. Devolve o candidato pronto.

    A família é tudo o que fica FIXO aqui: transformação, `d`, `D`, `trend` e exógenas. Comparar
    AICc dentro dela é legítimo; entre elas, não — e é por isso que a CV existe.
    """
    P, D, Q = sazonal_estrutura
    sazonal = (P, D, Q, PERIODO_SAZONAL) if (P or D or Q) else (0, 0, 0, 0)
    limite_k = max(4, n_ajuste // 6)

    melhor, melhor_aicc = None, np.inf
    for p in range(0, p_max + 1):
        for q in range(0, q_max + 1):
            if p == 0 and q == 0 and not (P or Q):
                continue
            if p + q + P + Q + len(exog) > limite_k:
                continue
            cand = Sarimax((p, d, q), sazonal, trend, transformacao, exog)
            estado = cand.ajustar(grupo, prioridade, horizonte, n_ajuste)
            if estado is None or not np.isfinite(estado["aic"]):
                continue
            valor = aicc(estado["aic"], estado["k"], n_ajuste)
            if valor < melhor_aicc:
                melhor, melhor_aicc = cand, valor
    return melhor, melhor_aicc


# --- ETS ----------------------------------------------------------------------------------

class Ets:
    """Suavização exponencial com tendência amortecida — a família desenhada para nível em deriva."""

    familia = "ETS"

    def __init__(self, tendencia=None, amortecida=False, sazonal=None, transformacao="nenhuma"):
        self.tendencia = tendencia
        self.amortecida = amortecida
        self.sazonal = sazonal
        self.transformacao = transformacao
        self.custo = (2 + (2 if tendencia else 0) + (1 if amortecida else 0)
                      + (7 if sazonal else 0) + (1 if transformacao != "nenhuma" else 0))
        self.rotulo = (f"ETS|t={tendencia}{'+amort' if amortecida else ''}"
                       f"|s={sazonal}|{transformacao}")

    def _montar(self, y_t):
        return ETSModel(y_t, error="add", trend=self.tendencia,
                        damped_trend=self.amortecida if self.tendencia else False,
                        seasonal=self.sazonal,
                        seasonal_periods=PERIODO_SAZONAL if self.sazonal else None)

    def ajustar(self, grupo, prioridade, horizonte, n_ajuste):
        if ETSModel is None:
            return None
        y = SERIES[(grupo, prioridade)][COLUNA_SERIE[horizonte]].astype(float).to_numpy()
        y_t = aplicar(y[:n_ajuste], self.transformacao)
        try:
            res = self._montar(y_t).fit(disp=False)
            params = np.asarray(res.params, dtype=float)
            if not np.all(np.isfinite(params)):
                return None
        except Exception:
            return None
        return {"params": params, "aic": float(res.aic), "k": len(params), "n_ajuste": n_ajuste}

    def prever(self, estado, grupo, prioridade, horizonte, origem):
        passos = HORIZONTES[horizonte]
        y = SERIES[(grupo, prioridade)][COLUNA_SERIE[horizonte]].astype(float).to_numpy()
        y_t = aplicar(y[:origem + 1], self.transformacao)
        res = self._montar(y_t).smooth(estado["params"])
        caminho = np.asarray(res.forecast(steps=passos), dtype=float)
        return desfazer(caminho[-1], self.transformacao)


# --- Theta --------------------------------------------------------------------------------

class Theta:
    """Método Theta. Reajusta a cada origem porque é fechado e custa quase nada."""

    familia = "Theta"

    def __init__(self, periodo=PERIODO_SAZONAL, desazonalizar=True, transformacao="nenhuma"):
        self.periodo = periodo
        self.desazonalizar = desazonalizar
        self.transformacao = transformacao
        self.custo = 3 + (1 if transformacao != "nenhuma" else 0)
        self.rotulo = f"Theta|s={periodo if desazonalizar else 0}|{transformacao}"

    def ajustar(self, grupo, prioridade, horizonte, n_ajuste):
        return {} if ThetaModel is not None else None

    def prever(self, estado, grupo, prioridade, horizonte, origem):
        passos = HORIZONTES[horizonte]
        y = SERIES[(grupo, prioridade)][COLUNA_SERIE[horizonte]].astype(float).to_numpy()
        y_t = aplicar(y[:origem + 1], self.transformacao)
        modelo = ThetaModel(y_t, period=self.periodo,
                            deseasonalize=self.desazonalizar, use_test=False)
        caminho = np.asarray(modelo.fit().forecast(steps=passos), dtype=float)
        return desfazer(caminho[-1], self.transformacao)


# --- pisos ingênuos -------------------------------------------------------------------------

class Ingenuo:
    """Os pisos. Não viram artefato — existem para dizer se o resto valeu a pena."""

    familia = "Ingênuo"

    def __init__(self, regra):
        self.regra = regra
        self.custo = 0
        self.rotulo = f"Ingênuo|{regra}"

    def ajustar(self, grupo, prioridade, horizonte, n_ajuste):
        return {}

    def prever(self, estado, grupo, prioridade, horizonte, origem):
        s = SERIES[(grupo, prioridade)]
        if self.regra == "último valor":
            return float(s.abertos.iloc[origem])
        if self.regra == "soma da última semana":
            return float(s.soma7.iloc[origem])
        if self.regra == "7 x abertos[D]":
            return float(7 * s.abertos.iloc[origem])
        if self.regra == "mesmo dia da semana passada":
            j = origem + HORIZONTES[horizonte] - 7
            return float(s[COLUNA_SERIE[horizonte]].iloc[max(j, 0)])
        if self.regra == "média das últimas 4 semanas":
            col = COLUNA_SERIE[horizonte]
            passos = HORIZONTES[horizonte]
            js = [origem + passos - 7 * k for k in range(1, 5)]
            js = [j for j in js if j >= 0]
            return float(np.mean([s[col].iloc[j] for j in js])) if js else float(s[col].iloc[origem])
        if self.regra == "média móvel 7d":
            return float(s.soma7.iloc[origem] / 7.0)
        raise ValueError(self.regra)


REGRAS_INGENUAS = {
    "D+1": ["último valor", "mesmo dia da semana passada", "média das últimas 4 semanas",
            "média móvel 7d"],
    "D+7": ["soma da última semana", "7 x abertos[D]", "mesmo dia da semana passada",
            "média das últimas 4 semanas"],
}
