"""Onda B — ETS amortecido e Theta.

Duas famílias que a safra atual nunca testou e que atacam exatamente o modo de falha observado:
nível que se desloca e precisa ser seguido sem que a extrapolação exploda. ARIMA com `d=1` segue
o nível mas projeta a última deriva para sempre; o ETS amortecido segue e desacelera.

Theta entra como piso forte, não como aposta: é o método que venceu a competição M3 e serve para
dizer se o esforço em SARIMAX se pagou. Se um piso vencer alguma série, isso vai no relatório.
"""
import time
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from candidatos import Ets, Theta
from dados import GRUPOS, HORIZONTES, PRIORIDADES, RAIZ, forca_sazonal_semanal
from protocolo import avaliar_multi, blocos_cv, serializar_erros

SAIDA = RAIZ / "experimentos" / "resultados"
TRANSFORMACOES = ["nenhuma", "log1p"]
TENDENCIAS = [(None, False), ("add", False), ("add", True)]
LIMIAR_SAZONAL = 0.05


def processar(tarefa):
    grupo, prioridade, horizonte = tarefa
    inicio = time.time()
    blocos = blocos_cv(grupo, prioridade, horizonte)
    eta2 = forca_sazonal_semanal(grupo, prioridade, horizonte)
    sazonais = [None, "add"] if (horizonte == "D+1" and eta2 > LIMIAR_SAZONAL) else [None]

    candidatos = [Ets(t, amort, sz, tr)
                  for tr in TRANSFORMACOES for t, amort in TENDENCIAS for sz in sazonais]
    candidatos += [Theta(desazonalizar=dz, transformacao=tr)
                   for tr in TRANSFORMACOES for dz in (True, False)]

    linhas = []
    for cand in candidatos:
        r = avaliar_multi(cand, grupo, prioridade, horizonte, blocos)
        if r is None:
            continue
        linhas.append({"grupo": grupo, "prio": prioridade, "horizonte": horizonte,
                       "familia": cand.familia, "rotulo": cand.rotulo,
                       "transformacao": cand.transformacao, "ordem": "", "sazonal": "",
                       "trend": "", "custo": cand.custo, "mae_cv": r["mae"],
                       "erro_padrao_cv": r["erro_padrao"], "n_cv": r["n"],
                       "eta2_dow": eta2, "n_blocos": r["n_blocos"],
                       "erros": serializar_erros(r["erros"])})

    print(f"  {grupo:16s} P{prioridade} {horizonte}  {len(linhas):3d} candidatos, "
          f"{time.time()-inicio:6.1f}s", flush=True)
    return linhas


if __name__ == "__main__":
    SAIDA.mkdir(parents=True, exist_ok=True)
    tarefas = [(g, p, h) for h in HORIZONTES for g in GRUPOS for p in PRIORIDADES]
    print(f"Onda B — {len(tarefas)} tarefas\n")
    inicio = time.time()
    with ProcessPoolExecutor(max_workers=6) as executor:
        blocos = list(executor.map(processar, tarefas))
    tudo = pd.DataFrame([l for bloco in blocos for l in bloco])
    tudo.to_csv(SAIDA / "onda_b.csv", sep=";", index=False, encoding="utf-8-sig")
    print(f"\n{len(tudo)} linhas em {time.time()-inicio:.0f}s -> resultados/onda_b.csv")
