"""Onda D — combinação de previsões e reconciliação de baixo para cima.

Duas respostas ao mesmo diagnóstico. As ondas A a C mostraram séries em que a CV elege um
vencedor que não sobrevive ao hold-out: `sem_intervencao P3 D+1` sai de MAE 33 na validação para
76 no teste. Não é o modelo que está errado, é a ESCOLHA que é instável — com 21 a 42 origens,
qual candidato fica em primeiro lugar é em boa parte sorte.

1. **Combinação.** Em vez de apostar no primeiro colocado, tirar a média dos K primeiros. É o
   resultado mais replicado da literatura de previsão: a combinação raramente é a melhor, e quase
   nunca é a pior — e o que mata este projeto são as vezes em que a escolha é a pior.

2. **De baixo para cima.** `total` é, por construção, `com_intervencao + sem_intervencao`. Dá
   para modelá-lo direto (é o que a safra atual faz) ou somar as duas previsões. A soma deixa a
   parte previsível ser prevista bem: `com_intervencao P3` tem sazonalidade semanal forte e o
   agregado dilui isso no ruído da outra fatia.

Como sempre, tudo decidido na CV; o hold-out só mede.
"""
import numpy as np
import pandas as pd

from candidatos import Ingenuo
from consolidar import carregar, reconstruir
from dados import GRUPOS, HORIZONTES, PRIORIDADES, RAIZ
from protocolo import avaliar, origens_cv, origens_teste, origens_treino, resumir

SAIDA = RAIZ / "experimentos" / "resultados"
TOPO = 8


def previsoes(candidato, g, p, h, origens):
    r = avaliar(candidato, g, p, h, origens)
    return None if r is None else np.asarray(r["previstos"], dtype=float)


def melhores_distintos(tudo, g, p, h, quantos=TOPO):
    """Os `quantos` melhores candidatos distintos por MAE de CV, pisos incluídos.

    O piso entra na combinação de propósito: quando nada supera o ingênuo numa série, a média
    puxada por ele é o comportamento certo, não uma concessão.
    """
    sub = tudo[(tudo.grupo == g) & (tudo.prio == p) & (tudo.horizonte == h)]
    sub = sub.sort_values("mae_cv").drop_duplicates("rotulo")
    return sub.head(quantos).to_dict("records")


def combinacoes(matriz, rotulos):
    """Médias e medianas dos K primeiros. `matriz[j]` são as previsões do j-ésimo colocado."""
    saida = {}
    for k in (2, 3, 5):
        if len(matriz) >= k:
            saida[f"média top{k}"] = (np.mean(matriz[:k], axis=0), rotulos[:k])
    for k in (3, 5):
        if len(matriz) >= k:
            saida[f"mediana top{k}"] = (np.median(matriz[:k], axis=0), rotulos[:k])
    return saida


def piso_da_safra(g, p, h):
    return Ingenuo("último valor" if h == "D+1" else
                   min(["soma da última semana", "7 x abertos[D]"],
                       key=lambda rg: avaliar(Ingenuo(rg), g, p, h, origens_treino(g, p, h))["mae"]))


def avaliar_serie(tudo, g, p, h):
    """Compara, na CV, o melhor individual contra cada combinação. Devolve a linha vencedora."""
    passos = HORIZONTES[h]
    orig_cv, orig_te = origens_cv(g, p, h), origens_teste(g, p, h)
    topo = melhores_distintos(tudo, g, p, h)

    membros, rotulos = [], []
    for linha in topo:
        cand = reconstruir(linha)
        pcv = previsoes(cand, g, p, h, orig_cv)
        if pcv is None:
            continue
        membros.append((cand, pcv, linha["rotulo"]))
    if not membros:
        return None

    reais_cv = np.array([avaliar(membros[0][0], g, p, h, orig_cv)["reais"]]).ravel()
    matriz_cv = np.array([m[1] for m in membros])
    rotulos = [m[2] for m in membros]

    opcoes = {f"individual: {rotulos[0]}": (matriz_cv[0], [rotulos[0]])}
    opcoes.update(combinacoes(matriz_cv, rotulos))

    avaliadas = {nome: (resumir(reais_cv, prev, passos)["mae"], usados)
                 for nome, (prev, usados) in opcoes.items()}
    nome_vencedor = min(avaliadas, key=lambda n: avaliadas[n][0])
    mae_cv, usados = avaliadas[nome_vencedor]

    # hold-out, uma vez
    por_rotulo = {m[2]: m[0] for m in membros}
    prev_teste = np.array([previsoes(por_rotulo[r], g, p, h, orig_te) for r in usados])
    reais_te = np.asarray(avaliar(por_rotulo[usados[0]], g, p, h, orig_te)["reais"], dtype=float)
    combinada = (np.median(prev_teste, axis=0) if nome_vencedor.startswith("mediana")
                 else np.mean(prev_teste, axis=0))
    mae_teste = resumir(reais_te, combinada, passos)["mae"]
    mae_piso = avaliar(piso_da_safra(g, p, h), g, p, h, orig_te)["mae"]

    return {"grupo": g, "prio": p, "horizonte": h, "estrategia": nome_vencedor,
            "n_membros": len(usados), "membros": " + ".join(usados),
            "mae_cv": mae_cv, "mae_teste": mae_teste, "mae_teste_piso": mae_piso,
            "ganho_pct": 100 * (1 - mae_teste / mae_piso),
            "previstos_teste": combinada, "reais_teste": reais_te}


if __name__ == "__main__":
    tudo = carregar(["onda_a", "onda_b", "onda_c"])
    tudo = tudo[np.isfinite(tudo.mae_cv)]

    linhas = [r for h in HORIZONTES for g in GRUPOS for p in PRIORIDADES
              if (r := avaliar_serie(tudo, g, p, h)) is not None]
    res = pd.DataFrame(linhas)

    # --- de baixo para cima: total = com + sem, previsão a previsão -------------------------
    por_chave = {(r["grupo"], r["prio"], r["horizonte"]): r for r in linhas}
    for h in HORIZONTES:
        for p in PRIORIDADES:
            com = por_chave.get(("com_intervencao", p, h))
            sem = por_chave.get(("sem_intervencao", p, h))
            tot = por_chave.get(("total", p, h))
            if not (com and sem and tot):
                continue
            # As janelas de teste diferem: `com_intervencao` tem 42/36 origens e as outras 28/22.
            # A soma só é definida onde as duas existem — alinhamos pelo fim, que é comum.
            n = min(len(com["previstos_teste"]), len(sem["previstos_teste"]),
                    len(tot["previstos_teste"]))
            soma = com["previstos_teste"][-n:] + sem["previstos_teste"][-n:]
            reais = tot["reais_teste"][-n:]
            mae_bu = resumir(reais, soma, HORIZONTES[h])["mae"]
            direto = resumir(reais, tot["previstos_teste"][-n:], HORIZONTES[h])["mae"]
            res.loc[(res.grupo == "total") & (res.prio == p) & (res.horizonte == h),
                    "mae_teste_baixo_para_cima"] = mae_bu
            res.loc[(res.grupo == "total") & (res.prio == p) & (res.horizonte == h),
                    "mae_teste_direto_mesma_janela"] = direto

    saida = res.drop(columns=["previstos_teste", "reais_teste"])
    saida.to_csv(SAIDA / "onda_d.csv", sep=";", index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 220)
    colunas = ["grupo", "prio", "horizonte", "estrategia", "n_membros", "mae_cv", "mae_teste",
               "mae_teste_piso", "ganho_pct"]
    print(saida[colunas].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print(f"\nvence o piso: {int((saida.ganho_pct > 0).sum())} de {len(saida)}")
    print(f"combinação escolhida pela CV em {int((saida.n_membros > 1).sum())} de {len(saida)} séries")
    print(f"MAE total no hold-out: {saida.mae_teste.sum():.0f} | piso {saida.mae_teste_piso.sum():.0f}")

    bu = saida.dropna(subset=["mae_teste_baixo_para_cima"])
    if len(bu):
        print("\nDe baixo para cima (total = com + sem), na janela comum:")
        print(bu[["prio", "horizonte", "mae_teste_direto_mesma_janela",
                  "mae_teste_baixo_para_cima"]].to_string(index=False,
                                                          float_format=lambda v: f"{v:.2f}"))
