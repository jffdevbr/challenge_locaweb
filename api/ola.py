"""Risco de queda do cumprimento de OLA.

As faixas foram calibradas sobre o **acumulado anual da prioridade inteira** — as duas fatias de
`tipo_tratamento` somadas. Aplicá-las dentro do grão do tipo daria número sem significado de
negócio, e é por isso que o atingimento vive em tabela própria (`s_fato_ola_prioridade`).

A projeção tem duas pernas e só a primeira vem de modelo:

1. **perna do modelo** — a previsão de `abertos` do horizonte escolhido, convertida em
   fechamentos pela razão `fechados/abertos` das últimas 28 dias, e daí em violações pela razão
   `violação/fechamento` da mesma janela;
2. **perna da extrapolação** — o resto do período à taxa diária média das últimas 28 dias.

A segunda perna é extrapolação de taxa, não previsão. O painel diz isso na cara.
"""

import numpy as np
import pandas as pd

from api import config as cfg
from api import previsao as prev

REGRAS = {
    "duracao": {
        "faixas": cfg.FAIXAS_OLA_DURACAO,
        "coluna_acumulada": "kpi_violado_prioridade_ac_ano",
        "coluna_diaria": "kpi_violado_prioridade",
        "unidade": "violações de KPI",
        "descricao": "acumulado anual de incidentes com KPI de duração violado",
    },
    "volume": {
        "faixas": cfg.FAIXAS_OLA_VOLUME,
        "coluna_acumulada": "fechados_prioridade_ac_ano",
        "coluna_diaria": "fechados_prioridade",
        "unidade": "fechamentos",
        "descricao": "acumulado anual de incidentes fechados",
    },
}


def atingimento(acumulado, cortes):
    """Traduz um acumulado em % de atingimento. Mais acumulado = faixa pior."""
    idx = int(np.searchsorted(np.asarray(cortes), float(acumulado), side="right"))
    return float(cfg.ESCALA_OLA[idx])


def painel(dominio, modelos, prioridade, data, horizonte, fim):
    ola = dominio.ola
    linha = ola[(ola.prioridade == prioridade) & (ola.data == data)]
    if linha.empty:
        return {"data": data.date().isoformat(), "prioridade": prioridade, "regras": {},
                "avisos": [{"nivel": "critico",
                            "texto": f"{data:%d/%m/%Y} não existe na tabela de OLA."}]}
    linha = linha.iloc[0]

    taxas = _taxas(dominio, prioridade, data)
    taxas_recentes = _taxas(dominio, prioridade, data, dias=7)
    modelo = _perna_do_modelo(dominio, modelos, prioridade, data, horizonte, taxas)
    dias_totais = int((fim - data).days)

    avisos = []
    if modelo["previsao_abertos"] is None:
        avisos.append({"nivel": "atencao",
                       "texto": "Sem previsão utilizável nesta data: a projeção usa só a "
                                "extrapolação de taxa histórica."})

    regras = {}
    for nome, spec in REGRAS.items():
        regras[nome] = _projetar_regra(nome, spec, linha, prioridade, taxas, taxas_recentes,
                                       modelo, dias_totais, data, fim, avisos)

    return {
        "data": data.date().isoformat(),
        "prioridade": prioridade,
        "horizonte": horizonte,
        "fim_da_projecao": fim.date().isoformat(),
        "dias_projetados": dias_totais,
        "taxas_recentes": taxas,
        "taxas_ultimos_7_dias": taxas_recentes,
        "perna_do_modelo": modelo,
        "regras": regras,
        "avisos": avisos,
        "nota_de_metodo": (
            "Só a primeira perna da projeção vem de modelo (os próximos "
            f"{modelo['dias_cobertos']} dias). O restante é extrapolação da taxa diária das "
            f"últimas {cfg.JANELA_TAXA_DIAS} dias, com a dispersão histórica dessa taxa."
        ),
    }


# ==================================================================================================
# Taxas recentes e perna do modelo
# ==================================================================================================

def _taxas(dominio, prioridade, data, dias=cfg.JANELA_TAXA_DIAS):
    """Taxas de conversão e diárias de uma janela retroativa fechando na data de origem."""
    inicio = data - pd.Timedelta(days=dias - 1)

    o = dominio.ola
    jan_ola = o[(o.prioridade == prioridade) & (o.data.between(inicio, data))]

    f = dominio.fato
    jan_fato = f[(f.prioridade == prioridade) & (f.data.between(inicio, data))]
    abertos = float(jan_fato.abertos.sum())

    fechados_dia = jan_ola.fechados_prioridade.astype(float)
    violacoes_dia = jan_ola.kpi_violado_prioridade.astype(float)
    fechados = float(fechados_dia.sum())

    return {
        "janela_dias": int(len(jan_ola)),
        "abertos_no_periodo": abertos,
        "fechados_no_periodo": fechados,
        "violacoes_no_periodo": float(violacoes_dia.sum()),
        "fechados_por_aberto": round(fechados / abertos, 4) if abertos > 0 else None,
        "violacoes_por_fechado": round(violacoes_dia.sum() / fechados, 6) if fechados > 0 else 0.0,
        "fechados_por_dia": {"media": round(float(fechados_dia.mean()), 2),
                             "desvio": round(float(fechados_dia.std(ddof=1) or 0.0), 2)},
        "violacoes_por_dia": {"media": round(float(violacoes_dia.mean()), 3),
                              "desvio": round(float(violacoes_dia.std(ddof=1) or 0.0), 3)},
    }


def _tendencia(base, recente, campo):
    """A taxa recente está acelerando em relação à janela longa?

    Existe porque uma janela de 28 dias achata o começo de uma escalada — e é exatamente aí que
    o alerta precisaria sair. Comparar as duas janelas não fabrica previsão nenhuma: só mostra
    que as duas leituras discordam, e deixa a decisão com quem lê.
    """
    lento = base[campo]["media"]
    rapido = recente[campo]["media"]
    if lento <= 0:
        return {"razao": None, "leitura": "sem base de comparação",
                "media_longa": lento, "media_recente": rapido}
    razao = rapido / lento
    if razao >= 1.5:
        leitura = "acelerando — a taxa recente é bem maior que a da janela longa"
    elif razao <= 0.67:
        leitura = "desacelerando"
    else:
        leitura = "estável"
    return {"razao": round(razao, 2), "leitura": leitura,
            "media_longa": lento, "media_recente": rapido}


def _perna_do_modelo(dominio, modelos, prioridade, data, horizonte, taxas):
    """A previsão do horizonte, convertida em fechamentos — a única parte que vem de modelo."""
    passos = cfg.HORIZONTES[horizonte]
    r = prev.prever(dominio, modelos, "total", prioridade, horizonte, data,
                    alfa=cfg.ALFA_BANDA_TELA)
    if r["previsao"] is None or r["usou_fallback"]:
        return {"previsao_abertos": None, "fechados_previstos": None, "desvio_fechados": None,
                "dias_cobertos": 0, "selo": r["situacao"]["selo"]}

    razao = taxas["fechados_por_aberto"] or 0.0
    # Desvio implícito na banda: metade da largura dividida pelo z da confiança usada.
    z = 1.2816   # bicaudal a 80 %
    largura = r["banda"]["superior"] - r["banda"]["inferior"]
    desvio_abertos = max(largura / (2 * z), 0.0)

    return {
        "previsao_abertos": r["previsao"],
        "banda_abertos": r["banda"],
        "fechados_por_aberto": razao,
        "fechados_previstos": round(r["previsao"] * razao, 2),
        "desvio_fechados": round(desvio_abertos * razao, 2),
        "dias_cobertos": passos,
        "selo": r["situacao"]["selo"],
        "modelo": r["modelo"],
        "supera_ingenuo": r["desempenho_no_teste"]["supera_ingenuo"],
    }


# ==================================================================================================
# Projeção de uma regra
# ==================================================================================================

def _projetar_regra(nome, spec, linha, prioridade, taxas, taxas_recentes, modelo, dias_totais,
                    data, fim, avisos):
    cortes = spec["faixas"].get(prioridade)
    acumulado = float(linha[spec["coluna_acumulada"]])

    if cortes is None:
        avisos.append({
            "nivel": "atencao",
            "texto": (f"P{prioridade} não tem faixa de OLA definida na regra de {nome} — é a "
                      "origem dos 33,3 % de nulo em `s_fato_ola_prioridade`. Pendência aberta "
                      "com a área; o painel não inventa meta."),
        })
        return {"tem_meta": False, "acumulado_hoje": acumulado,
                "unidade": spec["unidade"], "descricao": spec["descricao"]}

    hoje = atingimento(acumulado, cortes)
    estourada = acumulado > cortes[-1]
    if estourada:
        avisos.append({
            "nivel": "critico",
            "texto": (f"Regra de {nome} da P{prioridade}: o acumulado ({acumulado:,.0f} "
                      f"{spec['unidade']}) já passou o corte máximo ({cortes[-1]:,.0f}). O "
                      "atingimento está em 0 % e não há mais faixa para onde cair — sem "
                      "gradiente de risco. As faixas foram calibradas para outra escala de "
                      "volume e precisam de recalibração com a área.").replace(",", "."),
        })

    proximo = _proximo_corte(acumulado, cortes)
    incremento = _sortear_incremento(nome, taxas, modelo, dias_totais)

    projetado = acumulado + incremento["media"]
    faixas_sorteadas = [atingimento(acumulado + x, cortes) for x in incremento["amostras"]]
    distribuicao = _distribuicao(faixas_sorteadas)
    piora = float(np.mean([f < hoje for f in faixas_sorteadas]))

    # Cenário alternativo à taxa dos últimos 7 dias. Não substitui o cenário base — convive com
    # ele. Quando os dois discordam muito, é a discordância que é a informação.
    campo = "fechados_por_dia" if nome == "volume" else "violacoes_por_dia"
    tendencia = _tendencia(taxas, taxas_recentes, campo)
    inc_recente = _sortear_incremento(nome, taxas_recentes, modelo, dias_totais)
    faixas_recentes = [atingimento(acumulado + x, cortes) for x in inc_recente["amostras"]]
    cenario_recente = {
        "base_da_taxa": "últimos 7 dias",
        "acumulado_esperado": round(acumulado + inc_recente["media"], 1),
        "atingimento_esperado_pct": atingimento(acumulado + inc_recente["media"], cortes),
        "probabilidade_de_piorar": round(float(np.mean([f < hoje for f in faixas_recentes])), 3),
        "dias_ate_o_corte": _dias_ate(proximo, acumulado, inc_recente["media_diaria"]),
        "data_provavel_de_cruzamento": _data_cruzamento(
            proximo, acumulado, inc_recente["media_diaria"], data, fim),
        "tendencia": tendencia,
    }
    if tendencia["razao"] and tendencia["razao"] >= 1.5 and cenario_recente[
            "probabilidade_de_piorar"] > piora + 0.15:
        avisos.append({
            "nivel": "critico",
            "texto": (f"Regra de {nome} da P{prioridade}: a taxa dos últimos 7 dias é "
                      f"{tendencia['razao']:.1f}× a da janela de {cfg.JANELA_TAXA_DIAS} dias. No "
                      f"cenário base o risco de cair de faixa é {piora:.0%}; à taxa recente é "
                      f"{cenario_recente['probabilidade_de_piorar']:.0%}. A janela longa está "
                      "achatando uma escalada em curso."),
        })

    return {
        "cenario_taxa_recente": cenario_recente,
        "tem_meta": True,
        "unidade": spec["unidade"],
        "descricao": spec["descricao"],
        "cortes": cortes,
        "escala": cfg.ESCALA_OLA,
        "acumulado_hoje": acumulado,
        "atingimento_hoje_pct": hoje,
        "faixa_estourada": estourada,
        "proximo_corte": proximo,
        "orcamento_restante": (None if proximo is None
                               else round(proximo - acumulado, 2)),
        "dias_ate_o_corte": _dias_ate(proximo, acumulado, incremento["media_diaria"]),
        "data_provavel_de_cruzamento": _data_cruzamento(
            proximo, acumulado, incremento["media_diaria"], data, fim),
        "projecao": {
            "acumulado_esperado": round(projetado, 1),
            "atingimento_esperado_pct": atingimento(projetado, cortes),
            "incremento_esperado": round(incremento["media"], 1),
            "p05": round(acumulado + float(np.percentile(incremento["amostras"], 5)), 1),
            "p95": round(acumulado + float(np.percentile(incremento["amostras"], 95)), 1),
        },
        "probabilidade_de_piorar": round(piora, 3),
        "distribuicao_de_faixas": distribuicao,
    }


def _sortear_incremento(nome, taxas, modelo, dias_totais):
    """Monte Carlo do incremento do acumulado até o fim do período.

    Perna 1 (coberta pelo modelo): normal em torno do previsto, com o desvio implícito na banda.
    Perna 2 (resto): normal em torno da taxa diária média, com desvio crescendo com a raiz do
    número de dias — soma de dias aproximadamente independentes.

    Nas violações, a conversão fechamento -> violação entra como Poisson: são eventos raros
    (dezenas por ano), e a discretização importa perto de um corte.
    """
    rng = np.random.default_rng(42)
    n = cfg.SORTEIOS_MONTE_CARLO

    dias_modelo = min(modelo["dias_cobertos"], dias_totais)
    dias_resto = max(dias_totais - dias_modelo, 0)

    if dias_modelo > 0 and modelo["fechados_previstos"] is not None:
        perna1 = rng.normal(modelo["fechados_previstos"],
                            max(modelo["desvio_fechados"], 1e-9), n)
    else:
        perna1 = np.zeros(n)
        dias_resto = dias_totais

    media_dia = taxas["fechados_por_dia"]["media"]
    desvio_dia = taxas["fechados_por_dia"]["desvio"]
    perna2 = rng.normal(media_dia * dias_resto,
                        max(desvio_dia * np.sqrt(max(dias_resto, 1)), 1e-9), n)

    fechados = np.clip(perna1 + perna2, 0, None)

    if nome == "volume":
        amostras = fechados
        media_diaria = media_dia
    else:
        taxa = taxas["violacoes_por_fechado"]
        amostras = rng.poisson(np.clip(fechados * taxa, 0, None)).astype(float)
        media_diaria = taxas["violacoes_por_dia"]["media"]

    return {"amostras": amostras, "media": float(amostras.mean()), "media_diaria": media_diaria}


def _proximo_corte(acumulado, cortes):
    """O corte imediatamente acima do acumulado — o que separa da faixa de baixo."""
    acima = [c for c in cortes if c > acumulado]
    return float(min(acima)) if acima else None


def _dias_ate(proximo, acumulado, media_diaria):
    if proximo is None or not media_diaria:
        return None
    return round((proximo - acumulado) / media_diaria, 1)


def _data_cruzamento(proximo, acumulado, media_diaria, data, fim):
    dias = _dias_ate(proximo, acumulado, media_diaria)
    if dias is None or dias < 0:
        return None
    alvo = data + pd.Timedelta(days=int(np.ceil(dias)))
    return {"data": alvo.date().isoformat(), "dentro_da_projecao": bool(alvo <= fim)}


def _distribuicao(faixas_sorteadas):
    serie = pd.Series(faixas_sorteadas)
    contagem = serie.value_counts(normalize=True).sort_index(ascending=False)
    return [{"atingimento_pct": float(k), "probabilidade": round(float(v), 3)}
            for k, v in contagem.items()]
