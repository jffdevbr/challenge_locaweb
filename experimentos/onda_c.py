"""Onda C — exógenas, onde elas são legítimas, sem criar nenhuma feature.

Parte da melhor estrutura que a onda A encontrou para cada série e acrescenta exógenas por
seleção progressiva guiada pelo MAE de CV. Sem threshold de correlação, sem p-valor: o critério
é o erro fora da amostra, que é o que se quer minimizar.

Dois blocos de candidatas, e a diferença entre eles é a razão de a onda existir:

- **calendário** — conhecido para qualquer data futura, entra sem defasagem;
- **estado observado em D** (`backlog`, `fechados`, as três razões `inc_por_*`, ...) — entra
  defasado de `h` dias, na forma `<c>_obs<h>`. Assim, a exógena que o modelo lê no passo D+k é o
  valor de D+k-h, que já era conhecido na origem. Estas nunca chegaram a um SARIMAX na safra
  atual: eram exclusividade do LSTM, que perdeu em quase toda série.

No fim do caminho progressivo, a ordem (p,q) é rebuscada por AICc já com as exógenas escolhidas —
acrescentar regressor muda a estrutura de erro que sobra para o ARMA modelar.
"""
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from candidatos import Sarimax, buscar_ordem
from dados import (FEATURES_OBSERVADAS, GRUPOS, HORIZONTES, N_TREINO, PRIORIDADES, RAIZ,
                   SERIES)
from protocolo import (avaliar, blocos_cv, escolher_pareado, janela_ajuste,
                       melhora_significativa, resumir, serializar_erros)

SAIDA = RAIZ / "experimentos" / "resultados"

CALENDARIO = {
    "D+1": ["feriado", "vespera_feriado", "pos_feriado", "dia_util", "fim_de_semana",
            "num_dia_util", "sen_semana", "cos_semana"],
    "D+7": ["feriados_7d", "vesperas_7d", "dias_uteis_7d", "sen_ano", "cos_ano"],
}
MAX_EXOG = 3
Q_MAX = {"D+1": 3, "D+7": 9}


def pool(horizonte):
    h = HORIZONTES[horizonte]
    return CALENDARIO[horizonte] + [f"{c}_obs{h}" for c in FEATURES_OBSERVADAS]


def base_da_onda_a(grupo, prioridade, horizonte):
    """A estrutura vencedora da onda A para esta série — ponto de partida, não de chegada."""
    tab = pd.read_csv(SAIDA / "onda_a.csv", sep=";")
    sub = tab[(tab.grupo == grupo) & (tab.prio == prioridade)
              & (tab.horizonte == horizonte) & (tab.familia == "SARIMAX")]
    if sub.empty:
        return None
    linha = escolher_pareado(sub.to_dict("records"), passos=HORIZONTES[horizonte])
    return linha


def processar(tarefa):
    grupo, prioridade, horizonte = tarefa
    inicio = time.time()
    base = base_da_onda_a(grupo, prioridade, horizonte)
    if base is None:
        return []
    ordem, sazonal = eval(base["ordem"]), eval(base["sazonal"])
    trend, transformacao = base["trend"], base["transformacao"]
    blocos = blocos_cv(grupo, prioridade, horizonte)
    n_aj = N_TREINO[(grupo, prioridade)]
    passos = HORIZONTES[horizonte]

    # Uma ordem por bloco, buscada na janela daquele bloco e sem exógenas. É o mesmo cuidado da
    # onda A: pontuar um bloco com ordem escolhida em dado posterior a ele seria vazamento.
    ordens_bloco = []
    for bloco in blocos:
        cand_b, _ = buscar_ordem(grupo, prioridade, horizonte, janela_ajuste(bloco),
                                 transformacao, ordem[1], trend, sazonal_estrutura=sazonal[:3],
                                 q_max=Q_MAX[horizonte])
        ordens_bloco.append(cand_b.ordem if cand_b is not None else ordem)

    def medir(exog):
        """MAE de CV do conjunto `exog`, medido em todos os blocos."""
        previstos, reais = [], []
        for bloco, ordem_b in zip(blocos, ordens_bloco):
            r_b = avaliar(Sarimax(ordem_b, sazonal, trend, transformacao, tuple(exog)),
                          grupo, prioridade, horizonte, bloco)
            if r_b is None:
                return None
            previstos.extend(r_b["previstos"])
            reais.extend(r_b["reais"])
        saida = resumir(reais, previstos, passos)
        saida["erros"] = np.abs(np.asarray(previstos) - np.asarray(reais))
        return saida

    # Candidatas com variação na janela de ajuste — coluna constante não informa nada. Nulo
    # esparso é tolerado (as razões `inc_por_*` são nulas em dia sem incidente, e `matriz_exog`
    # já as zera); nulo em massa não, porque aí a coluna vira ruído padronizado.
    s = SERIES[(grupo, prioridade)]
    disponiveis = [c for c in pool(horizonte)
                   if c in s.columns and s[c].iloc[:n_aj].nunique(dropna=True) > 1
                   and s[c].iloc[:n_aj].isna().mean() < 0.20]

    caminho, escolhidas = [], []
    linha_base = {"grupo": grupo, "prio": prioridade, "horizonte": horizonte,
                  "familia": "SARIMAX", "transformacao": transformacao,
                  "ordem": str(ordem), "sazonal": str(sazonal), "trend": trend}
    r0 = medir(())
    if r0 is None:
        return []
    caminho.append({**linha_base, "rotulo": f"C|{ordem}|{transformacao}|exog=[]", "exog": "()",
                    "custo": sum(ordem[::2]) + sum(sazonal[:3]), "mae_cv": r0["mae"],
                    "erro_padrao_cv": r0["erro_padrao"], "n_cv": r0["n"], "n_exog": 0,
                    "erros": serializar_erros(r0["erros"])})

    melhor_mae, erros_atuais = r0["mae"], r0["erros"]
    passos = HORIZONTES[horizonte]
    for _ in range(MAX_EXOG):
        ganhador, ganho_mae, ganho_r = None, melhor_mae, None
        for c in disponiveis:
            if c in escolhidas:
                continue
            r = medir(escolhidas + [c])
            # Só entra quem melhora ALÉM do próprio ruído da diferença pareada. Sem esse portão,
            # a busca progressiva encontra ganho em qualquer coluna e leva o modelo a decorar a
            # janela de validação.
            if (r is not None and r["mae"] < ganho_mae
                    and melhora_significativa(r["erros"], erros_atuais, passos)):
                ganhador, ganho_mae, ganho_r = c, r["mae"], r
        if ganhador is None:
            break
        erros_atuais = ganho_r["erros"]
        escolhidas.append(ganhador)
        melhor_mae = ganho_mae
        caminho.append({**linha_base,
                        "rotulo": f"C|{ordem}|{transformacao}|exog={escolhidas}",
                        "exog": str(tuple(escolhidas)),
                        "custo": sum(ordem[::2]) + sum(sazonal[:3]) + len(escolhidas),
                        "mae_cv": ganho_r["mae"], "erro_padrao_cv": ganho_r["erro_padrao"],
                        "n_cv": ganho_r["n"], "n_exog": len(escolhidas),
                        "erros": serializar_erros(ganho_r["erros"])})

    # Rebusca de (p,q) na janela de treino inteira, já com as exógenas escolhidas: acrescentar
    # regressor muda a estrutura de erro que sobra para o ARMA modelar. Isto altera a ordem que
    # VAI A PRODUÇÃO, não o escore de CV — o escore continua sendo o do procedimento, com ordem
    # buscada bloco a bloco.
    if escolhidas:
        cand, _ = buscar_ordem(grupo, prioridade, horizonte, n_aj, transformacao,
                               ordem[1], trend, sazonal_estrutura=sazonal[:3],
                               q_max=Q_MAX[horizonte], exog=tuple(escolhidas))
        if cand is not None:
            caminho[-1]["ordem"] = str(cand.ordem)
            caminho[-1]["custo"] = cand.custo
            caminho[-1]["rotulo"] = f"C|{cand.ordem}|{transformacao}|exog={escolhidas}"

    print(f"  {grupo:16s} P{prioridade} {horizonte}  {len(disponiveis):2d} candidatas -> "
          f"{escolhidas}  MAE {r0['mae']:.2f} -> {melhor_mae:.2f}  "
          f"{time.time()-inicio:6.1f}s", flush=True)
    return caminho


if __name__ == "__main__":
    SAIDA.mkdir(parents=True, exist_ok=True)
    tarefas = [(g, p, h) for h in HORIZONTES for g in GRUPOS for p in PRIORIDADES]
    print(f"Onda C — {len(tarefas)} tarefas\n")
    inicio = time.time()
    with ProcessPoolExecutor(max_workers=6) as executor:
        blocos = list(executor.map(processar, tarefas))
    tudo = pd.DataFrame([l for bloco in blocos for l in bloco])
    tudo.to_csv(SAIDA / "onda_c.csv", sep=";", index=False, encoding="utf-8-sig")
    print(f"\n{len(tudo)} linhas em {time.time()-inicio:.0f}s -> resultados/onda_c.csv")
