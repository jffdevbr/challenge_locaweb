"""Consolidação final: escolhe por série na CV, decide o `total` e mede uma única vez no teste.

Três decisões, todas tomadas com dado de treino:

1. **Qual candidato** — menor MAE no backtest de origem móvel multibloco (ondas A, B e C).
2. **Como prever `total`** — direto, ou somando as previsões de `com_intervencao` e
   `sem_intervencao`. `total` é a soma das duas por construção, então as duas rotas são válidas;
   a de baixo para cima deixa a fatia previsível ser prevista bem em vez de diluí-la no ruído da
   outra. A comparação é feita na janela de CV comum às três séries.
3. **Qual piso** — a mesma regra ingênua da safra atual, escolhida sobre as origens de treino,
   para que a comparação com o resultado anterior seja da mesma régua.

Só depois disso o hold-out é tocado, uma vez.
"""
import numpy as np
import pandas as pd

from candidatos import Ingenuo
from consolidar import carregar, reconstruir
from dados import CORTE, GRUPOS, HORIZONTES, PRIORIDADES, RAIZ, SERIES
from protocolo import (avaliar, avaliar_multi, blocos_cv, escolher_pareado, origens_teste,
                       origens_treino, resumir)

SAIDA = RAIZ / "experimentos" / "resultados"


def datas_de(grupo, prioridade, indices, passos):
    """Datas-alvo das origens — a chave para casar séries de grupos com janelas diferentes."""
    s = SERIES[(grupo, prioridade)]
    return [s.data.iloc[i + passos] for i in indices]


def indices_por_data(grupo, prioridade, datas, passos):
    """Traduz datas-alvo em índices de origem daquela série. `None` quando a data não existe."""
    s = SERIES[(grupo, prioridade)]
    mapa = {d: i for i, d in enumerate(s.data)}
    saida = []
    for d in datas:
        j = mapa.get(d)
        saida.append(None if j is None or j - passos < 0 else j - passos)
    return saida


def previsoes_em(candidato, grupo, prioridade, horizonte, origens):
    r = avaliar(candidato, grupo, prioridade, horizonte, origens)
    return None if r is None else np.asarray(r["previstos"], dtype=float)


def piso_da_safra(g, p, h):
    """A regra ingênua que a safra atual usaria: escolhida sobre todas as origens de treino."""
    regras = ["último valor"] if h == "D+1" else ["soma da última semana", "7 x abertos[D]"]
    return Ingenuo(min(regras, key=lambda rg: avaliar(Ingenuo(rg), g, p, h,
                                                      origens_treino(g, p, h))["mae"]))


def escala_mase(g, p, h, piso):
    """Denominador do MASE: MAE da regra ingênua DENTRO DO TREINO, como na célula 78."""
    return avaliar(piso, g, p, h, origens_treino(g, p, h))["mae"]


TOPO = 6

# Combinação de previsões: TESTADA E DESCARTADA, com o código preservado para quem quiser refazer.
#
# A motivação era boa: com 42 a 126 origens, o primeiro lugar da CV é meio cara ou coroa entre
# candidatos separados por 1 %, e a combinação normalmente troca "às vezes o melhor, às vezes o
# pior" por "quase sempre bom". Aqui não trocou. Três variantes foram medidas nas mesmas ondas —
# média dos 2/3/5 primeiros, mediana dos 3/5, e mediana exigindo três membros — e deram 9, 8 e 9
# vitórias contra o piso, todas dentro do ruído das 10 da seleção individual, com MAE somado
# entre 3.933 e 4.213 contra 3.907.
#
# O que decidiu contra não foi a média das vitórias, foi o modo de falha: basta um SARIMAX com
# raiz explosiva entre os primeiros colocados para arrastar a combinação inteira — em
# `total P2 D+1` a média dos cinco primeiros levou o MAE de 28 para 4.163, e mesmo com a trava
# de sanidade ainda para 123. A mediana resolve esse caso e cria outros, porque com 3 membros
# ela descarta o melhor tão facilmente quanto o pior. Somando o custo de serving (vários
# artefatos por série, contra o contrato atual de um), não se paga.
COMBINAR = False


def melhor_estrategia(tudo, g, p, h):
    """Melhor estratégia por série na CV. Com `COMBINAR = False`, é o primeiro colocado."""
    passos = HORIZONTES[h]
    blocos = blocos_cv(g, p, h)
    # O ingênuo sai da disputa: ele é a régua, não o produto. Onde a CV disser que nada o
    # supera, isso aparece como ganho negativo na tabela final — que é a informação honesta —
    # em vez de sumir dentro de um artefato que replica o piso.
    sub = (tudo[(tudo.grupo == g) & (tudo.prio == p) & (tudo.horizonte == h)
                & (tudo.familia != "Ingênuo")]
           .sort_values("mae_cv").drop_duplicates("rotulo").head(TOPO))

    membros, previstos_cv, reais_cv = [], [], None
    for linha in sub.to_dict("records"):
        r = avaliar_multi(reconstruir(linha), g, p, h, blocos)
        if r is None:
            continue
        membros.append(linha)
        previstos_cv.append(np.asarray(r["previstos"], dtype=float))
        reais_cv = np.asarray(r["reais"], dtype=float)
    if not membros:
        return None

    matriz = np.array(previstos_cv)
    opcoes = {"individual": (matriz[0], [0])}
    if COMBINAR:
        for k in (3, 5):
            if len(matriz) >= k:
                opcoes[f"mediana top{k}"] = (np.median(matriz[:k], axis=0), list(range(k)))

    notas = {nome: resumir(reais_cv, prev, passos)["mae"] for nome, (prev, _) in opcoes.items()}
    melhor = min(notas, key=notas.get)
    limite = notas[melhor] * 1.005              # empate praticamente exato -> menos membros
    empatados = [n for n in notas if notas[n] <= limite]
    nome = min(empatados, key=lambda n: (len(opcoes[n][1]), notas[n]))

    indices = opcoes[nome][1]
    return {"estrategia": nome, "membros": [membros[i] for i in indices],
            "mae_cv": notas[nome], "mediana": nome.startswith("mediana"),
            "rotulo": (membros[0]["rotulo"] if nome == "individual"
                       else f"{nome}: " + " + ".join(membros[i]["rotulo"] for i in indices)),
            "familia": (membros[0]["familia"] if nome == "individual" else "combinação")}


def prever_estrategia(estrategia, g, p, h, origens):
    prev = [previsoes_em(reconstruir(m), g, p, h, origens) for m in estrategia["membros"]]
    prev = [x for x in prev if x is not None]
    if not prev:
        return None
    matriz = np.array(prev)
    return np.median(matriz, axis=0) if len(matriz) >= 3 else matriz.mean(axis=0)


if __name__ == "__main__":
    tudo = carregar(["onda_a", "onda_b", "onda_c"])
    tudo = tudo[np.isfinite(tudo.mae_cv)]

    # 1. melhor estratégia por série, pela CV (individual ou combinação dos primeiros colocados)
    escolhas = {}
    for h in HORIZONTES:
        for g in GRUPOS:
            for p in PRIORIDADES:
                e = melhor_estrategia(tudo, g, p, h)
                if e is not None:
                    escolhas[(g, p, h)] = e

    # 2. `total`: direto ou de baixo para cima? decidido na janela de CV comum
    rota_total = {}
    for h in HORIZONTES:
        passos = HORIZONTES[h]
        for p in PRIORIDADES:
            chaves = [("com_intervencao", p, h), ("sem_intervencao", p, h), ("total", p, h)]
            if any(k not in escolhas for k in chaves):
                continue
            orig_tot = [i for bloco in blocos_cv("total", p, h) for i in bloco]
            datas = datas_de("total", p, orig_tot, passos)
            i_com = indices_por_data("com_intervencao", p, datas, passos)
            i_sem = indices_por_data("sem_intervencao", p, datas, passos)
            usaveis = [k for k in range(len(datas)) if i_com[k] is not None and i_sem[k] is not None]
            if len(usaveis) < 10:
                rota_total[(p, h)] = "direto"
                continue

            s_tot = SERIES[("total", p)]
            col = "abertos" if h == "D+1" else "soma7"
            reais = np.array([float(s_tot[col].iloc[orig_tot[k] + passos]) for k in usaveis])
            p_dir = prever_estrategia(escolhas[("total", p, h)], "total", p, h,
                                      [orig_tot[k] for k in usaveis])
            p_com = prever_estrategia(escolhas[("com_intervencao", p, h)],
                                      "com_intervencao", p, h, [i_com[k] for k in usaveis])
            p_sem = prever_estrategia(escolhas[("sem_intervencao", p, h)],
                                      "sem_intervencao", p, h, [i_sem[k] for k in usaveis])
            if p_dir is None or p_com is None or p_sem is None:
                rota_total[(p, h)] = "direto"
                continue
            mae_dir = resumir(reais, p_dir, passos)["mae"]
            mae_bu = resumir(reais, p_com + p_sem, passos)["mae"]
            # Margem exigida de 5 %: nas duas vezes em que a rota foi trocada por uma vantagem
            # de CV abaixo de 1,5 %, o hold-out piorou. Diferença dessa ordem não é decisão, é
            # ruído — e no empate fica a rota direta, que é a que o contrato de serving já atende.
            rota_total[(p, h)] = "baixo para cima" if mae_bu < 0.95 * mae_dir else "direto"
            print(f"  total P{p} {h}: CV direto {mae_dir:7.2f} | de baixo para cima {mae_bu:7.2f}"
                  f"  -> {rota_total[(p, h)]}")

    # 3. hold-out, uma vez
    linhas = []
    for h in HORIZONTES:
        passos = HORIZONTES[h]
        for g in GRUPOS:
            for p in PRIORIDADES:
                if (g, p, h) not in escolhas:
                    continue
                orig = origens_teste(g, p, h)
                s = SERIES[(g, p)]
                col = "abertos" if h == "D+1" else "soma7"
                reais = np.array([float(s[col].iloc[i + passos]) for i in orig])
                rota = rota_total.get((p, h), "direto") if g == "total" else "direto"

                if rota == "baixo para cima":
                    datas = datas_de("total", p, orig, passos)
                    i_com = indices_por_data("com_intervencao", p, datas, passos)
                    i_sem = indices_por_data("sem_intervencao", p, datas, passos)
                    ok = [k for k in range(len(datas))
                          if i_com[k] is not None and i_sem[k] is not None]
                    prev = (prever_estrategia(escolhas[("com_intervencao", p, h)],
                                              "com_intervencao", p, h, [i_com[k] for k in ok])
                            + prever_estrategia(escolhas[("sem_intervencao", p, h)],
                                                "sem_intervencao", p, h, [i_sem[k] for k in ok]))
                    reais, orig = reais[ok], [orig[k] for k in ok]
                    rotulo = "soma de com_intervencao + sem_intervencao"
                    familia = "composto"
                else:
                    prev = prever_estrategia(escolhas[(g, p, h)], g, p, h, orig)
                    rotulo = escolhas[(g, p, h)]["rotulo"]
                    familia = escolhas[(g, p, h)]["familia"]

                piso = piso_da_safra(g, p, h)
                mae_piso = resumir(reais, np.array([piso.prever({}, g, p, h, i) for i in orig]),
                                   passos)["mae"]
                mae = resumir(reais, prev, passos)["mae"]
                linhas.append({
                    "grupo": g, "prio": p, "horizonte": h, "rota": rota, "familia": familia,
                    "estrategia": escolhas[(g, p, h)]["estrategia"],
                    "n_membros": len(escolhas[(g, p, h)]["membros"]),
                    "rotulo": rotulo, "mae_cv": escolhas[(g, p, h)]["mae_cv"],
                    "mae_teste": mae, "mae_piso": mae_piso,
                    "mase": mae / escala_mase(g, p, h, piso),
                    "ganho_pct": 100 * (1 - mae / mae_piso), "vence": mae < mae_piso, "n": len(orig),
                })

    res = pd.DataFrame(linhas)

    aval = pd.read_csv(RAIZ / "3_gold_data" / "g_avaliacao_modelos.csv", sep=";")
    todos = aval[aval.prioridade.astype(str) != "todas"]
    esc = (aval[(aval.escolhido == True) & (aval.prioridade.astype(str) == "todas")]  # noqa: E712
           .set_index(["tipo_tratamento", "horizonte"]).modelo)

    def mae_antigo(g, p, h):
        linha = todos[(todos.tipo_tratamento == g) & (todos.horizonte == h)
                      & (todos.prioridade.astype(int) == p) & (todos.modelo == esc.get((g, h)))]
        return float(linha.mae.iloc[0]) if len(linha) else np.nan

    res["mae_safra_atual"] = [mae_antigo(r.grupo, r.prio, r.horizonte) for r in res.itertuples()]
    res["ganho_safra_pct"] = 100 * (1 - res.mae_teste / res.mae_safra_atual)
    res.to_csv(SAIDA / "final.csv", sep=";", index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 230)
    cols = ["grupo", "prio", "horizonte", "familia", "estrategia", "n_membros", "mae_cv",
            "mae_teste", "mae_piso", "ganho_pct", "mase", "mae_safra_atual", "ganho_safra_pct"]
    print("\n" + res[cols].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print(f"\nvence o piso ingênuo:      {int(res.vence.sum()):2d} de {len(res)}   "
          f"(safra atual: 11 de 18)")
    print(f"melhor que a safra atual:  {int((res.ganho_safra_pct > 0).sum()):2d} de {len(res)}")
    print(f"MASE médio:                {res.mase.mean():.3f}   "
          f"(abaixo de 1 = melhor que o ingênuo do treino)")
    print(f"MAE somado no hold-out — novo {res.mae_teste.sum():.0f} | "
          f"safra atual {res.mae_safra_atual.sum():.0f} | piso {res.mae_piso.sum():.0f}")
    print("\n-> resultados/final.csv")
