"""Consolida as ondas: escolhe por série pela CV e só então mede no hold-out.

A ordem importa e é o ponto do plano inteiro. Primeiro `escolher_pareado` decide, olhando
exclusivamente o MAE do backtest de origem móvel dentro do treino. Depois — e nunca antes — o
vencedor é levado ao conjunto de teste, uma vez. O teste não participa de nenhuma decisão.

Uso:  python consolidar.py [onda_a onda_b ...]
"""
import sys

import numpy as np
import pandas as pd

from candidatos import Ets, Ingenuo, Sarimax, Theta
from dados import GRUPOS, HORIZONTES, PRIORIDADES, RAIZ
from protocolo import avaliar, escolher_pareado, origens_teste, origens_treino

SAIDA = RAIZ / "experimentos" / "resultados"


def reconstruir(linha):
    """Recria o candidato a partir da linha de resultado. O rótulo é o contrato."""
    familia = linha["familia"]
    if familia == "SARIMAX":
        exog = linha.get("exog")
        exog = eval(exog) if isinstance(exog, str) and exog.strip() else ()
        return Sarimax(eval(linha["ordem"]), eval(linha["sazonal"]), linha["trend"],
                       linha["transformacao"], exog)
    if familia == "ETS":
        corpo = linha["rotulo"].split("|")
        tendencia = None if "t=None" in corpo[1] else "add"
        amortecida = "+amort" in corpo[1]
        sazonal = None if corpo[2] == "s=None" else "add"
        return Ets(tendencia, amortecida, sazonal, linha["transformacao"])
    if familia == "Theta":
        return Theta(desazonalizar=not linha["rotulo"].split("|")[1].endswith("=0"),
                     transformacao=linha["transformacao"])
    if familia == "Ingênuo":
        return Ingenuo(linha["rotulo"].split("|", 1)[1])
    raise ValueError(familia)


def carregar(ondas):
    quadros = []
    for onda in ondas:
        caminho = SAIDA / f"{onda}.csv"
        if caminho.exists():
            quadros.append(pd.read_csv(caminho, sep=";"))
        else:
            print(f"  (ausente: {caminho.name})")
    return pd.concat(quadros, ignore_index=True)


if __name__ == "__main__":
    ondas = sys.argv[1:] or ["onda_a", "onda_b", "onda_c"]
    tudo = carregar(ondas)
    tudo = tudo[np.isfinite(tudo.mae_cv)]

    linhas = []
    for h in HORIZONTES:
        for g in GRUPOS:
            for p in PRIORIDADES:
                sub = tudo[(tudo.grupo == g) & (tudo.prio == p) & (tudo.horizonte == h)]
                if sub.empty:
                    continue
                registros = sub.to_dict("records")
                modelos = [r for r in registros if r["familia"] != "Ingênuo"]
                pisos = [r for r in registros if r["familia"] == "Ingênuo"]

                escolhido = escolher_pareado(modelos, passos=HORIZONTES[h])
                piso_cv = min(pisos, key=lambda r: r["mae_cv"]) if pisos else None
                if escolhido is None:
                    continue

                orig_teste = origens_teste(g, p, h)
                r_modelo = avaliar(reconstruir(escolhido), g, p, h, orig_teste)
                # O piso do hold-out é a MESMA regra da safra atual: a que vence no treino.
                piso_antigo = Ingenuo("último valor" if h == "D+1" else
                                      min(["soma da última semana", "7 x abertos[D]"],
                                          key=lambda rg: avaliar(Ingenuo(rg), g, p, h,
                                                                 origens_treino(g, p, h))["mae"]))
                r_piso = avaliar(piso_antigo, g, p, h, orig_teste)
                r_piso_cv = avaliar(reconstruir(piso_cv), g, p, h, orig_teste) if piso_cv else None

                linhas.append({
                    "grupo": g, "prio": p, "horizonte": h,
                    "familia": escolhido["familia"], "rotulo": escolhido["rotulo"],
                    "mae_cv": escolhido["mae_cv"], "ep_cv": escolhido["erro_padrao_cv"],
                    "mae_cv_piso": piso_cv["mae_cv"] if piso_cv else np.nan,
                    "mae_teste": r_modelo["mae"],
                    "mae_teste_piso": r_piso["mae"],
                    "mae_teste_piso_forte": r_piso_cv["mae"] if r_piso_cv else np.nan,
                    "ganho_pct": 100 * (1 - r_modelo["mae"] / r_piso["mae"]),
                    "vence_piso": r_modelo["mae"] < r_piso["mae"],
                })

    res = pd.DataFrame(linhas)
    res.to_csv(SAIDA / "escolhidos.csv", sep=";", index=False, encoding="utf-8-sig")

    aval = pd.read_csv(RAIZ / "3_gold_data" / "g_avaliacao_modelos.csv", sep=";")
    antigo = aval[aval.escolhido == True]  # noqa: E712
    antigo = antigo[antigo.prioridade.astype(str) != "todas"]
    chave = antigo.set_index([antigo.tipo_tratamento, antigo.horizonte,
                              antigo.prioridade.astype(int)]).mae
    # o vencedor agregado da safra antiga, medido série a série
    todos = aval[aval.prioridade.astype(str) != "todas"]
    escolhas_antigas = (aval[(aval.escolhido == True) & (aval.prioridade.astype(str) == "todas")]  # noqa: E712
                        .set_index(["tipo_tratamento", "horizonte"]).modelo)
    def mae_antigo(g, p, h):
        modelo = escolhas_antigas.get((g, h))
        linha = todos[(todos.tipo_tratamento == g) & (todos.horizonte == h)
                      & (todos.prioridade.astype(int) == p) & (todos.modelo == modelo)]
        return float(linha.mae.iloc[0]) if len(linha) else np.nan

    res["mae_safra_atual"] = [mae_antigo(r.grupo, r.prio, r.horizonte)
                              for r in res.itertuples()]
    res["ganho_vs_safra_pct"] = 100 * (1 - res.mae_teste / res.mae_safra_atual)

    pd.set_option("display.width", 200)
    colunas = ["grupo", "prio", "horizonte", "familia", "rotulo", "mae_cv", "mae_teste",
               "mae_teste_piso", "ganho_pct", "mae_safra_atual", "ganho_vs_safra_pct"]
    print(res[colunas].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print(f"\nvence o piso ingênuo: {int(res.vence_piso.sum())} de {len(res)} séries "
          f"(safra atual: 11 de 18)")
    print(f"melhor que a safra atual: {int((res.ganho_vs_safra_pct > 0).sum())} de {len(res)}")
    print(f"MAE total no hold-out — novo {res.mae_teste.sum():.0f} | "
          f"safra atual {res.mae_safra_atual.sum():.0f} | piso {res.mae_teste_piso.sum():.0f}")
    res.to_csv(SAIDA / "escolhidos.csv", sep=";", index=False, encoding="utf-8-sig")
    print("\n-> resultados/escolhidos.csv")
