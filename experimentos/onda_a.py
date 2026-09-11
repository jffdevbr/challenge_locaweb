"""Onda A — estrutura do ajuste, sem nenhuma feature nova.

Varre, por série e horizonte, as famílias estruturais que a safra atual nunca testou:

    transformação {nenhuma, log1p} x (d, trend) {(0,c), (1,n), (1,drift)} x bloco sazonal

Dentro de cada família, (p,q) sai por AICc na janela de ajuste — comparação legítima, mesma
escala e mesmo `d`. ENTRE famílias quem decide é o MAE do backtest de origem móvel. É a inversão
que o plano propõe: o teste de hipótese (ADF) sai, o erro fora da amostra entra.

O bloco sazonal só é testado onde há sazonalidade semanal para capturar (η² do dia-da-semana
medido no treino acima de 0,05) e só no D+1 — `soma7` cobre sempre 7 dias consecutivos, portanto
sempre um de cada dia da semana, e o ciclo semanal não sobrevive à agregação.
"""
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from candidatos import Ingenuo, REGRAS_INGENUAS, buscar_ordem
from dados import (GRUPOS, HORIZONTES, N_TREINO, PRIORIDADES, RAIZ, forca_sazonal_semanal)
from protocolo import (avaliar, avaliar_multi, blocos_cv, janela_ajuste, resumir,
                       serializar_erros)

SAIDA = RAIZ / "experimentos" / "resultados"

TRANSFORMACOES = ["nenhuma", "log1p"]
TENDENCIAS = [(0, "c"), (1, "n"), (1, "t")]     # (d, trend); "t" com d=1 é drift
SAZONAIS = [(0, 0, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1)]
LIMIAR_SAZONAL = 0.05
Q_MAX = {"D+1": 3, "D+7": 9}                    # a grade antiga saturava em 7 nas 9 séries do D+7
P_MAX = {"D+1": 3, "D+7": 3}


def familias(grupo, prioridade, horizonte):
    eta2 = forca_sazonal_semanal(grupo, prioridade, horizonte)
    usar_sazonal = horizonte == "D+1" and eta2 > LIMIAR_SAZONAL
    blocos = SAZONAIS if usar_sazonal else [(0, 0, 0)]
    return [(t, d, trend, sz)
            for t in TRANSFORMACOES for d, trend in TENDENCIAS for sz in blocos], eta2


def processar(tarefa):
    grupo, prioridade, horizonte = tarefa
    inicio = time.time()
    blocos = blocos_cv(grupo, prioridade, horizonte)
    n_treino = N_TREINO[(grupo, prioridade)]
    combos, eta2 = familias(grupo, prioridade, horizonte)

    linhas = []
    for regra in REGRAS_INGENUAS[horizonte]:
        r = avaliar_multi(Ingenuo(regra), grupo, prioridade, horizonte, blocos)
        if r:
            linhas.append({"grupo": grupo, "prio": prioridade, "horizonte": horizonte,
                           "familia": "Ingênuo", "rotulo": f"Ingênuo|{regra}",
                           "transformacao": "nenhuma", "ordem": "", "sazonal": "", "trend": "",
                           "custo": 0, "mae_cv": r["mae"], "erro_padrao_cv": r["erro_padrao"],
                           "n_cv": r["n"], "n_blocos": r["n_blocos"], "eta2_dow": eta2,
                           "erros": serializar_erros(r["erros"])})

    for transformacao, d, trend, sz in combos:
        # A ordem é rebuscada DENTRO de cada bloco: usar uma ordem escolhida com dado posterior
        # para pontuar um bloco anterior seria vazamento — sutil, porque fica escondido numa
        # etapa que parece só de ajuste. O que a CV pontua aqui é o procedimento inteiro.
        previstos, reais = [], []
        for bloco in blocos:
            cand_b, _ = buscar_ordem(
                grupo, prioridade, horizonte, janela_ajuste(bloco), transformacao, d, trend,
                sazonal_estrutura=sz, q_max=Q_MAX[horizonte], p_max=P_MAX[horizonte])
            if cand_b is None:
                continue
            r_b = avaliar(cand_b, grupo, prioridade, horizonte, bloco)
            if r_b is None:
                continue
            previstos.extend(r_b["previstos"])
            reais.extend(r_b["reais"])
        if not previstos:
            continue
        r = resumir(reais, previstos, HORIZONTES[horizonte])
        erros = np.abs(np.asarray(previstos) - np.asarray(reais))

        # A ordem que vai a produção é a da janela de treino INTEIRA — mais dado, mesma família.
        final, valor_aicc = buscar_ordem(
            grupo, prioridade, horizonte, n_treino, transformacao, d, trend,
            sazonal_estrutura=sz, q_max=Q_MAX[horizonte], p_max=P_MAX[horizonte])
        if final is None:
            continue
        linhas.append({"grupo": grupo, "prio": prioridade, "horizonte": horizonte,
                       "familia": "SARIMAX", "rotulo": final.rotulo,
                       "transformacao": transformacao, "ordem": str(final.ordem),
                       "sazonal": str(final.sazonal), "trend": trend, "custo": final.custo,
                       "mae_cv": r["mae"], "erro_padrao_cv": r["erro_padrao"], "n_cv": r["n"],
                       "n_blocos": len(blocos), "aicc": valor_aicc, "eta2_dow": eta2,
                       "erros": serializar_erros(erros)})

    print(f"  {grupo:16s} P{prioridade} {horizonte}  {len(combos):2d} famílias x "
          f"{len(blocos)} blocos, {len(linhas):3d} linhas, {time.time()-inicio:6.1f}s",
          flush=True)
    return linhas


if __name__ == "__main__":
    SAIDA.mkdir(parents=True, exist_ok=True)
    tarefas = [(g, p, h) for h in HORIZONTES for g in GRUPOS for p in PRIORIDADES]
    print(f"Onda A — {len(tarefas)} tarefas\n")
    inicio = time.time()
    with ProcessPoolExecutor(max_workers=6) as executor:
        blocos = list(executor.map(processar, tarefas))
    tudo = pd.DataFrame([l for bloco in blocos for l in bloco])
    tudo.to_csv(SAIDA / "onda_a.csv", sep=";", index=False, encoding="utf-8-sig")
    print(f"\n{len(tudo)} linhas em {time.time()-inicio:.0f}s -> resultados/onda_a.csv")
