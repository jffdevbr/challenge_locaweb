"""Real × previsto: a série inteira ao lado do recorte de teste.

A motivação é boa e vale ser dita: 22 a 42 dias de teste, caindo sobre o Natal, é amostra pequena
demais para julgar um modelo sozinha. Ver a série inteira responde uma pergunta diferente e
complementar — o modelo acompanha o nível e o ritmo do histórico, ou ele só acertou (ou errou) um
mês atípico?

Cada figura tem, por prioridade, dois painéis:

  esquerda — a série inteira, com a região de teste sombreada. A previsão antes do corte é
             ajustada com parâmetros estimados NO TREINO, então ali ela é dentro da amostra:
             serve para ler nível, ritmo e sazonalidade, NÃO para medir acurácia. A faixa
             sombreada é a única parte fora da amostra, e é onde os números do relatório vivem.
  direita  — o recorte de teste, com o piso ingênuo e o modelo da safra anterior por cima, que é
             a comparação que decide substituição.

O aviso do painel esquerdo está escrito na própria figura. Um gráfico que mistura ajuste dentro e
fora da amostra sem dizer qual é qual induz a erro justamente quem não leu o código.
"""
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

from consolidar import carregar, reconstruir
from dados import COLUNA_SERIE, CORTE, GRUPOS, HORIZONTES, N_TREINO, PRIORIDADES, RAIZ, SERIES
from protocolo import avaliar, origens_teste

SAIDA = RAIZ / "experimentos" / "resultados"
FIGURAS = SAIDA / "figuras"
BURN_IN = 30          # origens iniciais descartadas: o filtro ainda está estabilizando o estado

COR = {"real": "#1f2933", "previsto": "#2f6f9f", "piso": "#b0b7bf", "antigo": "#c9792e",
       "teste": "#f2c94c"}


def serie_completa(candidato, g, p, h):
    """Previsão em TODA origem elegível, do burn-in ao fim da série."""
    s = SERIES[(g, p)]
    passos = HORIZONTES[h]
    origens = [i for i in range(BURN_IN, len(s) - passos)]
    # Parâmetros fixados na janela de TREINO, não na primeira origem do gráfico. Sem isto o
    # modelo seria estimado com ~30 pontos e um SARIMAX sazonal simplesmente degenera — foi o que
    # produziu a previsão colapsada em zero na primeira versão desta figura.
    r = avaliar(candidato, g, p, h, origens, n_ajuste=N_TREINO[(g, p)])
    if r is None:
        return None
    return pd.DataFrame({
        "data_alvo": [s.data.iloc[i + passos] for i in origens],
        "real": r["reais"], "previsto": r["previstos"]})


def painel(ax, dados, corte, titulo, coluna_extra=None, rotulos_extra=None):
    ax.plot(dados.data_alvo, dados.real, color=COR["real"], lw=1.4, label="real")
    ax.plot(dados.data_alvo, dados.previsto, color=COR["previsto"], lw=1.4, label="previsto")
    for col, (rot, cor) in zip(coluna_extra or [], rotulos_extra or []):
        ax.plot(dados.data_alvo, dados[col], color=cor, lw=1.1, ls="--", label=rot)
    if corte is not None and dados.data_alvo.min() < corte < dados.data_alvo.max():
        ax.axvspan(corte, dados.data_alvo.max(), color=COR["teste"], alpha=0.18, lw=0)
        ax.axvline(corte, color=COR["teste"], lw=1.2)
    ax.set_title(titulo, fontsize=9, loc="left")
    ax.yaxis.set_major_locator(MaxNLocator(4))
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25, lw=0.5)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)


def figura(g, h, escolhas, tudo, prev_gold):
    fig, eixos = plt.subplots(len(PRIORIDADES), 2, figsize=(13, 8),
                              gridspec_kw={"width_ratios": [2.4, 1]})
    for linha, p in enumerate(PRIORIDADES):
        esc = escolhas.get((g, p, h))
        if esc is None:
            continue
        base = tudo[(tudo.grupo == g) & (tudo.prio == p) & (tudo.horizonte == h)
                    & (tudo.rotulo == esc["rotulo"])]
        if base.empty:
            continue
        cand = reconstruir(base.iloc[0].to_dict())

        completa = serie_completa(cand, g, p, h)
        if completa is None:
            continue
        painel(eixos[linha, 0], completa, CORTE[g],
               f"P{p} — série inteira · {esc['rotulo'][:70]}")
        eixos[linha, 0].set_ylabel(COLUNA_SERIE[h], fontsize=8)

        # recorte de teste, com piso e safra anterior
        teste = completa[completa.data_alvo >= CORTE[g]].copy()
        sub = prev_gold[(prev_gold.tipo_tratamento == g) & (prev_gold.prioridade == p)
                        & (prev_gold.horizonte == h)]
        for nome, filtro in (("piso", sub.modelo == "Ingênuo"),
                             ("antigo", sub.escolhido == True)):   # noqa: E712
            col = sub[filtro][["data_alvo", "valor_previsto"]].rename(
                columns={"valor_previsto": nome})
            teste = teste.merge(col, on="data_alvo", how="left")
        extras = [c for c in ("piso", "antigo") if c in teste and teste[c].notna().any()]
        painel(eixos[linha, 1], teste, None, f"P{p} — só o teste (n={len(teste)})",
               extras, [("ingênuo", COR["piso"]), ("safra anterior", COR["antigo"])][:len(extras)])
        eixos[linha, 1].legend(fontsize=6.5, frameon=False, ncol=2)

    eixos[0, 0].legend(fontsize=7, frameon=False, ncol=2)
    fig.suptitle(f"{g} · {h} — real × previsto", fontsize=11, x=0.008, ha="left")
    fig.text(0.008, 0.955,
             "Painel esquerdo: antes da faixa sombreada a previsão é DENTRO da amostra "
             "(parâmetros estimados no treino) — leia nível e ritmo, não acurácia. "
             "A faixa sombreada é o hold-out.", fontsize=7.5, color="#5b6672")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    caminho = FIGURAS / f"{g}_{h.replace('+', '')}.png"
    fig.savefig(caminho, dpi=130)
    plt.close(fig)
    return caminho


if __name__ == "__main__":
    FIGURAS.mkdir(parents=True, exist_ok=True)
    tudo = carregar(["onda_a", "onda_b", "onda_c"])
    tudo = tudo[np.isfinite(tudo.mae_cv)]
    final = pd.read_csv(SAIDA / "final.csv", sep=";")
    escolhas = {(r.grupo, int(r.prio), r.horizonte): {"rotulo": r.rotulo}
                for r in final.itertuples()}

    prev_gold = pd.read_csv(RAIZ / "3_gold_data" / "g_previsoes.csv", sep=";",
                            parse_dates=["data"])
    prev_gold["data_alvo"] = prev_gold.data + prev_gold.horizonte.map(
        {"D+1": pd.Timedelta(days=0), "D+7": pd.Timedelta(days=7)})

    for h in HORIZONTES:
        for g in GRUPOS:
            print("  ", figura(g, h, escolhas, tudo, prev_gold), flush=True)
    print(f"\n-> {FIGURAS}")
