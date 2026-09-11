"""Prova que a infra reproduz a safra atual antes de tentar melhorá-la.

Refaz o candidato "ARIMA" da safra antiga — `d` pelo ADF, grade por AIC, sem transformação,
sem exógenas — avalia nas origens de TESTE e compara com `3_gold_data/g_avaliacao_modelos.csv`.
Se divergir, o motor está errado e qualquer ganho medido depois é ilusão.
"""
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

from candidatos import Sarimax
from dados import (COLUNA_SERIE, GRUPOS, HORIZONTES, N_TREINO, PRIORIDADES, RAIZ, SERIES)
from protocolo import avaliar, origens_cv, origens_teste, verificar_sem_vazamento


def d_pelo_adf(y, alfa=0.05):
    try:
        return 0 if adfuller(np.asarray(y, dtype=float), autolag="AIC")[1] < alfa else 1
    except Exception:
        return 1


def buscar_ordem_antiga(grupo, prioridade, horizonte, q_max):
    """Réplica literal de `buscar_ordem` da célula 60: grade por AIC, sem sazonal, sem exógenas."""
    n_aj = N_TREINO[(grupo, prioridade)]
    y = SERIES[(grupo, prioridade)][COLUNA_SERIE[horizonte]].astype(float).to_numpy()
    d = d_pelo_adf(y[:n_aj])
    melhor, melhor_aic = None, np.inf
    for p in range(0, 4):
        for q in range(0, q_max + 1):
            if p == 0 and q == 0:
                continue
            cand = Sarimax((p, d, q), (0, 0, 0, 0), "c" if d == 0 else "n", "nenhuma", ())
            estado = cand.ajustar(grupo, prioridade, horizonte, n_aj)
            if estado is None or not np.isfinite(estado["aic"]):
                continue
            if estado["aic"] < melhor_aic:
                melhor, melhor_aic = cand, estado["aic"]
    return melhor, d


if __name__ == "__main__":
    verificar_sem_vazamento()
    print("OK — nenhuma origem de CV toca o período de teste.\n")

    aval = pd.read_csv(RAIZ / "3_gold_data" / "g_avaliacao_modelos.csv", sep=";")
    ref = aval[(aval.modelo == "ARIMA") & (aval.prioridade.astype(str) != "todas")]
    ref = ref.set_index([ref.tipo_tratamento, ref.horizonte, ref.prioridade.astype(int)]).mae

    linhas = []
    for h in HORIZONTES:
        q_max = 3 if h == "D+1" else 7
        for g in GRUPOS:
            for p in PRIORIDADES:
                cand, d = buscar_ordem_antiga(g, p, h, q_max)
                if cand is None:
                    continue
                r = avaliar(cand, g, p, h, origens_teste(g, p, h))
                esperado = float(ref.get((g, h, p), np.nan))
                linhas.append({
                    "grupo": g, "prio": p, "horizonte": h, "ordem": str(cand.ordem), "d_adf": d,
                    "mae_replicado": r["mae"], "mae_notebook": esperado,
                    "dif_pct": 100 * abs(r["mae"] - esperado) / esperado,
                    "n_cv": len(origens_cv(g, p, h)), "n_teste": r["n"],
                })

    tab = pd.DataFrame(linhas)
    pd.set_option("display.width", 160)
    print(tab.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    pior = tab.dif_pct.max()
    print(f"\nmaior divergência: {pior:.3f}%")
    print("VEREDITO:", "OK — a infra reproduz a safra atual." if pior < 1.0
          else "FALHA — o motor diverge do notebook, investigar antes de seguir.")
