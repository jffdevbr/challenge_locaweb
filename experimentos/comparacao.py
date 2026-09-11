"""Antigo × novo, série a série: substituir só onde há motivo.

A pergunta é a certa: não faz sentido trocar um modelo que era melhor. Mas "melhor" com 22 a 42
pontos de teste precisa de mais que a comparação de dois MAE — a diferença tem de ser maior que o
ruído dela.

Por isso a comparação é PAREADA nas mesmas datas-alvo: para cada dia, `|erro_novo| − |erro_antigo|`.
A dificuldade daquele dia é comum aos dois e se cancela, o que reduz muito a variância. O erro
padrão da média dessas diferenças leva correção de Newey-West porque no D+7 janelas consecutivas
compartilham 6 dos 7 dias. O teste resultante é o de Diebold-Mariano.

Veredito por série:
  SUBSTITUIR  — novo melhor, e a diferença passa de 1,64 erro padrão (~90 % de confiança)
  MANTER      — antigo melhor pela mesma régua
  INDIFERENTE — a diferença não se distingue de ruído; na dúvida fica o que já está em produção
"""
import numpy as np
import pandas as pd

from consolidar import carregar, reconstruir
from dados import HORIZONTES, RAIZ, SERIES
from protocolo import avaliar, origens_teste, _vif_sobreposicao

SAIDA = RAIZ / "experimentos" / "resultados"
LIMIAR_T = 1.64


def previsoes_novas(esc, tudo, g, p, h):
    """Previsões do modelo novo no teste, indexadas pela DATA-ALVO."""
    base = tudo[(tudo.grupo == g) & (tudo.prio == p) & (tudo.horizonte == h)
                & (tudo.rotulo == esc.rotulo)]
    if base.empty:
        return None
    orig = origens_teste(g, p, h)
    r = avaliar(reconstruir(base.iloc[0].to_dict()), g, p, h, orig)
    s = SERIES[(g, p)]
    passos = HORIZONTES[h]
    datas = [s.data.iloc[i + passos] for i in orig]
    return pd.DataFrame({"data_alvo": datas, "previsto_novo": r["previstos"],
                         "real": r["reais"]})


if __name__ == "__main__":
    tudo = carregar(["onda_a", "onda_b", "onda_c"])
    tudo = tudo[np.isfinite(tudo.mae_cv)]
    final = pd.read_csv(SAIDA / "final.csv", sep=";")
    prev = pd.read_csv(RAIZ / "3_gold_data" / "g_previsoes.csv", sep=";", parse_dates=["data"])

    # ATENÇÃO: em `g_previsoes.csv` a coluna `data` não tem o mesmo significado nos dois
    # horizontes. No D+1 ela é a data-ALVO (`valor_real == abertos[data]`, confere em 42 de 42);
    # no D+7 ela é a data de ORIGEM (`valor_real == soma7[data + 7d]`, confere em 36 de 36).
    # Casar as duas tabelas por `data` sem corrigir isso descarta 7 dias em cada série do D+7 e,
    # pior, descarta justamente os primeiros — enviesando a comparação. Aqui tudo é reindexado
    # pela data-alvo explícita.
    prev["data_alvo"] = prev.data + prev.horizonte.map(
        {"D+1": pd.Timedelta(days=0), "D+7": pd.Timedelta(days=7)})

    antigos = prev[prev.escolhido == True]      # noqa: E712 — o que está em produção hoje
    ingenuos = prev[prev.modelo == "Ingênuo"]

    linhas = []
    for _, esc in final.iterrows():
        g, p, h = esc.grupo, int(esc.prio), esc.horizonte
        novo = previsoes_novas(esc, tudo, g, p, h)
        if novo is None:
            continue
        velho = antigos[(antigos.tipo_tratamento == g) & (antigos.prioridade == p)
                        & (antigos.horizonte == h)][["data_alvo", "valor_previsto", "modelo"]]
        piso = ingenuos[(ingenuos.tipo_tratamento == g) & (ingenuos.prioridade == p)
                        & (ingenuos.horizonte == h)][["data_alvo", "valor_previsto"]]
        if velho.empty:
            continue

        j = (novo.merge(velho.rename(columns={"valor_previsto": "previsto_velho"}),
                        on="data_alvo")
                 .merge(piso.rename(columns={"valor_previsto": "previsto_piso"}),
                        on="data_alvo", how="left"))
        if len(j) < 5:
            continue

        e_novo = (j.previsto_novo - j.real).abs().to_numpy()
        e_velho = (j.previsto_velho - j.real).abs().to_numpy()
        dif = e_novo - e_velho
        vif = _vif_sobreposicao(dif, HORIZONTES[h])
        ep = dif.std(ddof=1) / np.sqrt(max(len(dif) / vif, 2.0))
        t = dif.mean() / ep if ep > 0 else 0.0

        veredito = ("SUBSTITUIR" if t < -LIMIAR_T else
                    "MANTER" if t > LIMIAR_T else "INDIFERENTE")
        linhas.append({
            "grupo": g, "prio": p, "horizonte": h, "n": len(j),
            "modelo_antigo": velho.modelo.iloc[0], "modelo_novo": esc.familia,
            "mae_antigo": e_velho.mean(), "mae_novo": e_novo.mean(),
            "delta": dif.mean(), "delta_pct": 100 * (e_novo.mean() / e_velho.mean() - 1),
            "erro_padrao": ep, "t": t, "veredito": veredito,
            "mae_piso": (j.previsto_piso - j.real).abs().mean(),
        })

    c = pd.DataFrame(linhas)
    c.to_csv(SAIDA / "comparacao_antigo_novo.csv", sep=";", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 210)

    print("=" * 108)
    print("ANTIGO x NOVO — teste pareado nas mesmas datas-alvo (Diebold-Mariano, Newey-West)")
    print("=" * 108)
    print(c[["grupo", "prio", "horizonte", "n", "modelo_antigo", "modelo_novo", "mae_antigo",
             "mae_novo", "delta_pct", "t", "veredito", "mae_piso"]]
          .to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print(f"\nSUBSTITUIR: {(c.veredito == 'SUBSTITUIR').sum()}   "
          f"MANTER: {(c.veredito == 'MANTER').sum()}   "
          f"INDIFERENTE: {(c.veredito == 'INDIFERENTE').sum()}")
    print(f"MAE somado — antigo {c.mae_antigo.sum():.0f} | novo {c.mae_novo.sum():.0f} | "
          f"piso {c.mae_piso.sum():.0f}")

    # carteira mista: fica o melhor dos dois por série, decidido pelo veredito
    misto = np.where(c.veredito == "SUBSTITUIR", c.mae_novo, c.mae_antigo)
    print(f"MAE somado se trocarmos só onde o veredito manda: {misto.sum():.0f}")
    print("\n-> resultados/comparacao_antigo_novo.csv")
