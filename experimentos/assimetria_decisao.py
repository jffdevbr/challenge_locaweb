"""A tabela que decide: vale deslocar? vale trocar de modelo? quanto custa em MAE?

Para cada nível de assimetria `k` (subestimar custa k vezes mais que superestimar), compara três
políticas, todas com escolha e calibração feitas SÓ no treino e medidas uma vez no hold-out:

  A. modelo escolhido por MAE, sem deslocamento          — o que a sessão entregou até aqui
  B. modelo escolhido por MAE, deslocado para o quantil τ — mesma família, alvo corrigido
  C. modelo escolhido por pinball_τ, deslocado           — troca também o modelo

A régua é a perda pinball no próprio `k` do negócio. Reportar MAE junto é obrigatório: ele mostra
o preço da proteção, que é o que a pergunta "não numa proporção muito maior" quer saber.
"""
import numpy as np
import pandas as pd

from assimetria import (ASSIMETRIAS, deslocamento, diagnostico, escolher_sob_pinball, pinball,
                        previsoes_por_bloco)
from consolidar import carregar, reconstruir
from dados import HORIZONTES, RAIZ
from protocolo import avaliar, blocos_cv, origens_teste

SAIDA = RAIZ / "experimentos" / "resultados"
QUEBRADAS = {("sem_intervencao", 3), ("total", 3)}     # nível triplica dentro do teste


def no_teste(candidato, g, p, h, erros_cv, tau):
    r = avaliar(candidato, g, p, h, origens_teste(g, p, h))
    reais = np.asarray(r["reais"], float)
    prev = np.asarray(r["previstos"], float)
    return reais, np.maximum(prev + deslocamento(erros_cv, tau), 0.0)


if __name__ == "__main__":
    tudo = carregar(["onda_a", "onda_b", "onda_c"])
    tudo = tudo[np.isfinite(tudo.mae_cv)]
    final = pd.read_csv(SAIDA / "final.csv", sep=";")

    registros = []
    for _, esc in final.iterrows():
        g, p, h = esc.grupo, int(esc.prio), esc.horizonte
        base = tudo[(tudo.grupo == g) & (tudo.prio == p) & (tudo.horizonte == h)
                    & (tudo.rotulo == esc.rotulo)]
        if base.empty:
            continue
        cand_mae = reconstruir(base.iloc[0].to_dict())
        blocos = blocos_cv(g, p, h)
        partes = previsoes_por_bloco(cand_mae, g, p, h, blocos)
        erros_mae = np.concatenate([r - q for r, q in partes])

        for k, tau in ASSIMETRIAS.items():
            reais, sem_desloc = no_teste(cand_mae, g, p, h, erros_mae, 0.5)
            _, com_desloc = no_teste(cand_mae, g, p, h, erros_mae, tau)

            outro, _ = escolher_sob_pinball(tudo, g, p, h, tau)
            cand_pb = reconstruir(outro) if outro is not None else cand_mae
            partes_pb = previsoes_por_bloco(cand_pb, g, p, h, blocos)
            erros_pb = np.concatenate([r - q for r, q in partes_pb]) if partes_pb else erros_mae
            _, trocado = no_teste(cand_pb, g, p, h, erros_pb, tau)

            for politica, prev in (("A sem deslocamento", sem_desloc),
                                   ("B deslocado", com_desloc),
                                   ("C deslocado + troca", trocado)):
                d = diagnostico(reais, prev)
                registros.append({"grupo": g, "prio": p, "horizonte": h, "k": k, "tau": tau,
                                  "politica": politica, "pinball": pinball(reais, prev, tau),
                                  **d, "n": len(reais),
                                  "quebrada": (g, p) in QUEBRADAS})

    det = pd.DataFrame(registros)
    det.to_csv(SAIDA / "assimetria_decisao.csv", sep=";", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 210)

    def bloco(sub, titulo):
        print("\n" + "=" * 100)
        print(titulo)
        print("=" * 100)
        linhas = []
        for (k, pol), s in sub.groupby(["k", "politica"]):
            w = s.n
            linhas.append({"k": k, "política": pol,
                           "pinball_k": (s.pinball * w).sum() / w.sum(),
                           "MAE": (s.mae * w).sum() / w.sum(),
                           "% subestimado": (s.pct_subestimado * w).sum() / w.sum(),
                           "falta média/dia": (s.falta_media * w).sum() / w.sum(),
                           "sobra média/dia": (s.sobra_media * w).sum() / w.sum()})
        t = pd.DataFrame(linhas)
        base = t[t.política == "A sem deslocamento"].set_index("k")
        t["pinball vs A %"] = [100 * (r.pinball_k / base.loc[r.k, "pinball_k"] - 1)
                               for r in t.itertuples()]
        t["MAE vs A %"] = [100 * (r.MAE / base.loc[r.k, "MAE"] - 1) for r in t.itertuples()]
        print(t.sort_values(["k", "política"]).to_string(index=False,
                                                         float_format=lambda v: f"{v:.2f}"))

    bloco(det, "TODAS AS 18 SÉRIES")
    bloco(det[~det.quebrada], "AS 14 SÉRIES SEM QUEBRA ESTRUTURAL NO TESTE (exclui P3 sem/total)")

    print("\n" + "=" * 100)
    print("POR SÉRIE, EM k = 3 — política B (deslocar, sem trocar de modelo)")
    print("=" * 100)
    s3 = det[(det.k == 3) & (det.politica == "B deslocado")]
    a3 = det[(det.k == 3) & (det.politica == "A sem deslocamento")].set_index(
        ["grupo", "prio", "horizonte"])
    s3 = s3.assign(
        mae_sem=[a3.loc[(r.grupo, r.prio, r.horizonte), "mae"] for r in s3.itertuples()],
        sub_sem=[a3.loc[(r.grupo, r.prio, r.horizonte), "pct_subestimado"]
                 for r in s3.itertuples()])
    print(s3[["grupo", "prio", "horizonte", "sub_sem", "pct_subestimado", "mae_sem", "mae",
              "falta_media"]]
          .rename(columns={"sub_sem": "%sub antes", "pct_subestimado": "%sub depois",
                           "mae_sem": "MAE antes", "mae": "MAE depois",
                           "falta_media": "falta/dia"})
          .to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print("\n-> resultados/assimetria_decisao.csv")
