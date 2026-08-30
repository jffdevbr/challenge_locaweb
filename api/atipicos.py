"""Detector de dia atípico — o real caiu fora da banda de previsão.

Aqui o que importa não é acertar o ponto, é ter uma **banda calibrada**. Um modelo que erra o
nível mas acerta a dispersão continua sendo um bom detector, e é isso que torna utilizáveis os 5
dos 6 cortes em que a previsão perde para o baseline ingênuo.

Quando o dia estoura a banda, a leitura de concentração diz que tipo de estouro foi: `inc_por_ic`
alto significa muitos incidentes vindo de poucos itens de configuração — sinal de evento
sistêmico. 400 incidentes espalhados por 200 ICs é volume alto de operação normal; 400 em 3 ICs é
outra coisa. As três razões `inc_por_*` são o único ganho com significância estatística do
projeto, e este painel é onde elas viram produto.
"""

import numpy as np
import pandas as pd

from api import config as cfg
from api import dominio as dom
from api import previsao as prev

HORIZONTE = "D+1"


def varrer(dominio, modelos, grupo, prioridade, inicio, fim, alfa=cfg.ALFA_BANDA_ALERTA):
    s = dominio.serie(grupo, prioridade)
    mediana_concentracao = _mediana_movel_concentracao(s)

    dias = []
    for data_alvo in pd.date_range(inicio, fim, freq="D"):
        origem = data_alvo - pd.Timedelta(days=1)
        situacao = dom.classificar(dominio, grupo, prioridade, origem, HORIZONTE)
        if not situacao["pode_prever"] or not situacao["tem_real"]:
            continue

        r = prev.prever(dominio, modelos, grupo, prioridade, HORIZONTE, origem, alfa=alfa)
        if r["previsao"] is None or r["usou_fallback"]:
            continue

        real = r["real"]
        inferior, superior = r["banda"]["inferior"], r["banda"]["superior"]
        fora = real < inferior or real > superior
        if not fora:
            continue

        dias.append({
            "data": data_alvo.date().isoformat(),
            "selo": situacao["selo"],
            "previsto": r["previsao"],
            "banda": r["banda"],
            "real": real,
            "desvio_pct": _desvio_pct(real, inferior, superior),
            "direcao": "acima" if real > superior else "abaixo",
            "concentracao": _concentracao(s, data_alvo, mediana_concentracao),
        })

    return {
        "grupo": grupo,
        "prioridade": prioridade,
        "horizonte": HORIZONTE,
        "intervalo": {"inicio": inicio.date().isoformat(), "fim": fim.date().isoformat()},
        "confianca_da_banda_pct": round((1 - alfa) * 100),
        "dias_avaliados": int((fim - inicio).days) + 1,
        "atipicos": dias,
        "resumo": _resumo(dias, int((fim - inicio).days) + 1, alfa),
        "avisos": [{
            "nivel": "atencao",
            "texto": ("Um dia fora da banda é um candidato a investigar, não um diagnóstico. A "
                      "banda vem do modelo do grupo, e nos cortes em que ele perde para o "
                      "ingênuo a calibração da dispersão não foi validada separadamente."),
        }],
    }


def _desvio_pct(real, inferior, superior):
    """Quanto o real passou da borda mais próxima, em % dessa borda."""
    if real > superior:
        return round((real - superior) / max(superior, 1) * 100, 1)
    return round((real - inferior) / max(inferior, 1) * 100, 1)


def _mediana_movel_concentracao(s):
    """Mediana móvel de 90 dias de `inc_por_ic` — a referência de "dia normal" da série."""
    if "inc_por_ic" not in s.columns:
        return pd.Series(index=s.index, dtype=float)
    return s.inc_por_ic.rolling(cfg.JANELA_MEDIANA_CONCENTRACAO, min_periods=30).median()


def _concentracao(s, data, mediana_movel):
    achados = s.index[s.data == data]
    if not len(achados):
        return None
    i = int(achados[0])
    valor = s.inc_por_ic.iloc[i] if "inc_por_ic" in s.columns else np.nan
    referencia = mediana_movel.iloc[i] if len(mediana_movel) else np.nan

    if not np.isfinite(valor) or not np.isfinite(referencia) or referencia <= 0:
        return {"inc_por_ic": None, "mediana_90d": None, "razao": None,
                "leitura": "sem base de comparação"}

    razao = float(valor) / float(referencia)
    if razao >= 2.0:
        leitura = "sistêmico — poucos ICs concentrando o volume"
    elif razao >= 1.3:
        leitura = "concentração acima do normal"
    else:
        leitura = "difuso — volume espalhado, operação normal em escala"

    return {
        "inc_por_ic": round(float(valor), 2),
        "mediana_90d": round(float(referencia), 2),
        "razao": round(razao, 2),
        "ics_distintos": _int_ou_none(s.ics_distintos.iloc[i] if "ics_distintos" in s else None),
        "leitura": leitura,
    }


def _int_ou_none(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if np.isfinite(f) else None


def _resumo(dias, avaliados, alfa):
    esperado = avaliados * alfa
    sistemicos = [d for d in dias
                  if d["concentracao"] and (d["concentracao"]["razao"] or 0) >= 2.0]
    return {
        "atipicos": len(dias),
        "esperados_por_acaso": round(esperado, 1),
        "acima_da_banda": sum(1 for d in dias if d["direcao"] == "acima"),
        "abaixo_da_banda": sum(1 for d in dias if d["direcao"] == "abaixo"),
        "com_marca_de_sistemico": len(sistemicos),
        "leitura": (
            f"Com banda de {round((1 - alfa) * 100)} %, o acaso já produziria ~{esperado:.1f} "
            f"dias fora em {avaliados}. Foram {len(dias)}."
        ),
    }
