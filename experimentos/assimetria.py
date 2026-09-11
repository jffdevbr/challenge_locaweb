"""Erro assimétrico: subestimar a demanda custa mais que superestimar.

O MAE é minimizado pela MEDIANA da distribuição preditiva — por construção ele aceita errar para
baixo em metade dos dias. Se subestimar custa `k` vezes mais que superestimar, o alvo ótimo passa
a ser o **quantil τ = k/(k+1)** e a métrica correspondente é a perda pinball:

    pinball_τ(y, ŷ) = τ·(y − ŷ)      se y > ŷ   (subestimou: pesa τ)
                      (1−τ)·(ŷ − y)  se y ≤ ŷ   (superestimou: pesa 1−τ)

Com τ = 0,5 ela é o MAE dividido por dois. Isso dá um botão contínuo em vez de uma margem
arbitrária: k = 2 → τ = 0,667; k = 3 → τ = 0,75; k = 5 → τ = 0,833.

Duas rotas para produzir o quantil, e as duas são medidas aqui:

1. **Intervalo do próprio modelo** — SARIMAX devolve média e erro padrão da previsão, e o quantil
   sai de `média + z_τ · se`. Só vale se o intervalo for calibrado, o que é uma pergunta empírica
   e é respondida na tabela de cobertura.
2. **Deslocamento empírico** — somar à previsão o quantil τ dos erros observados na validação.
   Não depende de o resíduo ser normal, funciona para qualquer família e é o que sobra quando a
   rota 1 se mostra malcalibrada.

O deslocamento é estimado por bloco-fora (o bloco avaliado nunca entra no cálculo do próprio
deslocamento); para o hold-out, usa todos os blocos de CV.
"""
import numpy as np
import pandas as pd
from scipy import stats

from consolidar import carregar, reconstruir
from dados import COLUNA_SERIE, GRUPOS, HORIZONTES, PRIORIDADES, RAIZ, SERIES
from protocolo import avaliar, blocos_cv, origens_teste

SAIDA = RAIZ / "experimentos" / "resultados"

# k = quantas vezes subestimar custa mais que superestimar
ASSIMETRIAS = {1: 0.500, 2: 0.667, 3: 0.750, 5: 0.833}
NIVEIS_IC = [0.80, 0.95]
TOPO = 8


def pinball(reais, previstos, tau):
    d = np.asarray(reais, float) - np.asarray(previstos, float)
    return float(np.mean(np.maximum(tau * d, (tau - 1.0) * d)))


def diagnostico(reais, previstos):
    """Como o erro se reparte entre falta e sobra — a leitura operacional."""
    r, p = np.asarray(reais, float), np.asarray(previstos, float)
    falta = np.maximum(r - p, 0.0)
    sobra = np.maximum(p - r, 0.0)
    return {"mae": float(np.abs(r - p).mean()),
            "pct_subestimado": float((r > p).mean() * 100),
            "falta_media": float(falta.mean()),
            "sobra_media": float(sobra.mean()),
            "vies": float((p - r).mean())}


def previsoes_por_bloco(candidato, g, p, h, blocos):
    saida = []
    for bloco in blocos:
        r = avaliar(candidato, g, p, h, bloco)
        if r is None:
            return None
        saida.append((np.asarray(r["reais"], float), np.asarray(r["previstos"], float)))
    return saida


def deslocamento(erros, tau):
    """Quantil τ dos erros com sinal (real − previsto). Somar isto à previsão mira o quantil τ."""
    return float(np.quantile(np.asarray(erros, float), tau)) if len(erros) else 0.0


def escolher_sob_pinball(tudo, g, p, h, tau):
    """Melhor candidato sob pinball na CV, com deslocamento estimado bloco-fora.

    O conjunto vem dos `TOPO` melhores por MAE. Não é limitação séria: uma vez que o deslocamento
    recentra qualquer candidato no quantil desejado, o que sobra para diferenciar os modelos é a
    DISPERSÃO do erro — e é isso que o MAE já ordena. A assimetria é tratada pelo deslocamento,
    não pela escolha do modelo. A tabela de resultados confirma ou desmente isso.
    """
    blocos = blocos_cv(g, p, h)
    sub = (tudo[(tudo.grupo == g) & (tudo.prio == p) & (tudo.horizonte == h)
                & (tudo.familia != "Ingênuo")]
           .sort_values("mae_cv").drop_duplicates("rotulo").head(TOPO))

    melhor, melhor_nota = None, np.inf
    for linha in sub.to_dict("records"):
        partes = previsoes_por_bloco(reconstruir(linha), g, p, h, blocos)
        if partes is None:
            continue
        reais, ajustadas = [], []
        for i, (r_b, p_b) in enumerate(partes):
            fora = np.concatenate([partes[j][0] - partes[j][1]
                                   for j in range(len(partes)) if j != i]) \
                if len(partes) > 1 else (r_b - p_b)
            reais.append(r_b)
            ajustadas.append(p_b + deslocamento(fora, tau))
        nota = pinball(np.concatenate(reais), np.concatenate(ajustadas), tau)
        if nota < melhor_nota:
            melhor, melhor_nota = linha, nota
    return melhor, melhor_nota


def cobertura_sarimax(candidato, g, p, h, origens, niveis=NIVEIS_IC):
    """Cobertura empírica do intervalo analítico do SARIMAX. Só faz sentido para essa família.

    A previsão de ponto e o erro padrão saem do mesmo filtro de Kalman do serving. Com `log1p`, o
    intervalo é construído na escala transformada e trazido de volta com `expm1` — quantil é
    equivariante a transformação monótona, então isso é exato, não aproximação.
    """
    from candidatos import Sarimax, aplicar, desfazer
    if not isinstance(candidato, Sarimax):
        return None
    passos = HORIZONTES[h]
    y = SERIES[(g, p)][COLUNA_SERIE[h]].astype(float).to_numpy()
    from dados import N_TREINO
    estado = candidato.ajustar(g, p, h, N_TREINO[(g, p)])
    if estado is None:
        return None

    dentro = {n: [] for n in niveis}
    for i in origens:
        try:
            y_t = aplicar(y[:i + 1], candidato.transformacao)
            exog_h = exog_f = None
            if candidato.exog:
                from dados import matriz_exog
                x = (matriz_exog(g, p, candidato.exog) - estado["centro"]) / estado["escala"]
                exog_h, exog_f = x[:i + 1], x[i + 1: i + 1 + passos]
            pr = candidato._montar(y_t, exog_h).filter(estado["params"]) \
                          .get_forecast(steps=passos, exog=exog_f)
            media = float(np.asarray(pr.predicted_mean)[-1])
            se = float(np.asarray(pr.se_mean)[-1])
        except Exception:
            continue
        real = float(y[i + passos])
        for n in niveis:
            z = stats.norm.ppf(0.5 + n / 2)
            lo = desfazer(media - z * se, candidato.transformacao)
            hi = desfazer(media + z * se, candidato.transformacao)
            dentro[n].append(lo <= real <= hi)
    return {n: (100 * float(np.mean(v)) if v else np.nan) for n, v in dentro.items()}


if __name__ == "__main__":
    tudo = carregar(["onda_a", "onda_b", "onda_c"])
    tudo = tudo[np.isfinite(tudo.mae_cv)]
    final = pd.read_csv(SAIDA / "final.csv", sep=";")

    linhas, trocas, coberturas = [], [], []
    for _, esc in final.iterrows():
        g, p, h = esc.grupo, int(esc.prio), esc.horizonte
        passos = HORIZONTES[h]
        blocos = blocos_cv(g, p, h)
        base = tudo[(tudo.grupo == g) & (tudo.prio == p) & (tudo.horizonte == h)
                    & (tudo.rotulo == esc.rotulo)]
        if base.empty:
            continue
        cand = reconstruir(base.iloc[0].to_dict())

        partes = previsoes_por_bloco(cand, g, p, h, blocos)
        erros_cv = np.concatenate([r - q for r, q in partes])

        orig = origens_teste(g, p, h)
        rt = avaliar(cand, g, p, h, orig)
        reais_te = np.asarray(rt["reais"], float)
        prev_te = np.asarray(rt["previstos"], float)

        for k, tau in ASSIMETRIAS.items():
            s = deslocamento(erros_cv, tau)
            ajust = np.maximum(prev_te + s, 0.0)
            d = diagnostico(reais_te, ajust)
            linhas.append({"grupo": g, "prio": p, "horizonte": h, "k": k, "tau": tau,
                           "deslocamento": s, **d,
                           "pinball": pinball(reais_te, ajust, tau),
                           "n": len(reais_te)})

        # o vencedor muda sob a métrica assimétrica?
        for k in (3,):
            outro, _ = escolher_sob_pinball(tudo, g, p, h, ASSIMETRIAS[k])
            if outro is not None:
                trocas.append({"grupo": g, "prio": p, "horizonte": h,
                               "por_mae": esc.rotulo, "por_pinball": outro["rotulo"],
                               "mudou": outro["rotulo"] != esc.rotulo})

        cob_cv = cobertura_sarimax(cand, g, p, h, [i for b in blocos for i in b])
        cob_te = cobertura_sarimax(cand, g, p, h, orig)
        if cob_cv and cob_te:
            coberturas.append({"grupo": g, "prio": p, "horizonte": h,
                               "cob80_cv": cob_cv[0.80], "cob80_teste": cob_te[0.80],
                               "cob95_cv": cob_cv[0.95], "cob95_teste": cob_te[0.95]})

    det = pd.DataFrame(linhas)
    det.to_csv(SAIDA / "assimetria.csv", sep=";", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 200)

    print("=" * 96)
    print("TROCA-SE MAE POR PROTEÇÃO CONTRA SUBESTIMAÇÃO — média ponderada das 18 séries")
    print("=" * 96)
    resumo = []
    for k, sub in det.groupby("k"):
        w = sub.n
        resumo.append({"k (custo de faltar / custo de sobrar)": k, "tau": sub.tau.iloc[0],
                       "% dias subestimados": (sub.pct_subestimado * w).sum() / w.sum(),
                       "MAE": (sub.mae * w).sum() / w.sum(),
                       "falta média/dia": (sub.falta_media * w).sum() / w.sum(),
                       "sobra média/dia": (sub.sobra_media * w).sum() / w.sum()})
    r = pd.DataFrame(resumo)
    r["MAE vs k=1"] = 100 * (r.MAE / r.MAE.iloc[0] - 1)
    r["falta vs k=1"] = 100 * (r["falta média/dia"] / r["falta média/dia"].iloc[0] - 1)
    print(r.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    if coberturas:
        print("\n" + "=" * 96)
        print("O INTERVALO DO MODELO É CONFIÁVEL? cobertura empírica (%) — nominal 80 e 95")
        print("=" * 96)
        c = pd.DataFrame(coberturas)
        print(c.to_string(index=False, float_format=lambda v: f"{v:.1f}"))
        print(f"\nmédia: 80% nominal -> {c.cob80_cv.mean():.1f}% na CV, "
              f"{c.cob80_teste.mean():.1f}% no teste  |  "
              f"95% nominal -> {c.cob95_cv.mean():.1f}% na CV, {c.cob95_teste.mean():.1f}% no teste")

    t = pd.DataFrame(trocas)
    print("\n" + "=" * 96)
    print(f"O VENCEDOR MUDA SOB PINBALL (k=3)? mudou em {int(t.mudou.sum())} de {len(t)} séries")
    print("=" * 96)
    if t.mudou.any():
        print(t[t.mudou][["grupo", "prio", "horizonte", "por_mae", "por_pinball"]]
              .to_string(index=False))
    print("\n-> resultados/assimetria.csv")
