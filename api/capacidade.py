"""Da previsão para o dimensionamento do turno.

Só `com_intervencao` entra: `sem_intervencao` fecha sozinho via monitoramento e não consome
analista. Somar os dois aqui inflaria o quadro pela metade que ninguém trata.

⚠️ `duracao_mediana_h` é **tempo decorrido até o fechamento**, não esforço em mãos. Tratá-lo como
hora de trabalho superestima o dimensionamento, e é por isso que `fator_esforco` existe, é
parâmetro e aparece na resposta com o aviso junto. O número só vira dimensionamento depois que a
área calibrar esse fator uma vez.
"""

import numpy as np
import pandas as pd

from api import config as cfg
from api import previsao as prev

GRUPO = "com_intervencao"


def painel(dominio, modelos, prioridade, data, horizonte, jornada_h, ocupacao, fator_esforco):
    passos = cfg.HORIZONTES[horizonte]
    r = prev.prever(dominio, modelos, GRUPO, prioridade, horizonte, data)

    avisos = [{
        "nivel": "atencao",
        "texto": ("`duracao_mediana_h` mede o tempo decorrido entre abertura e fechamento, não o "
                  "esforço humano gasto no incidente. Enquanto a área não calibrar "
                  "`fator_esforco`, leia este painel como ordem de grandeza, não como quadro de "
                  "pessoal."),
    }]

    if r["previsao"] is None:
        return {"data": data.date().isoformat(), "prioridade": prioridade,
                "horizonte": horizonte, "dimensionamento": None,
                "avisos": avisos + [{"nivel": "critico", "texto": r["situacao"]["explicacao"]}]}

    if r["situacao"]["selo"] in (cfg.SELO_FORA_DA_JANELA, cfg.SELO_TREINO):
        avisos.append({"nivel": "atencao", "texto": r["situacao"]["explicacao"]})
    if not r["desempenho_no_teste"]["supera_ingenuo"]:
        avisos.append({
            "nivel": "critico",
            "texto": (f"A previsão que alimenta este dimensionamento não supera o baseline "
                      f"ingênuo neste corte ({r['desempenho_no_teste']['ganho_vs_ingenuo']:+.1f} "
                      "% de MAE). Considere dimensionar pelo ingênuo e usar o modelo só como "
                      "leitura de dispersão."),
        })

    duracao = _duracao_mediana(dominio, prioridade, data)
    if duracao is None:
        return {"data": data.date().isoformat(), "prioridade": prioridade,
                "horizonte": horizonte, "dimensionamento": None,
                "avisos": avisos + [{"nivel": "critico",
                                     "texto": "Sem duração mediana utilizável na janela recente."}]}

    incidentes = r["previsao"]
    horas = incidentes * duracao * fator_esforco
    capacidade_analista_dia = jornada_h * ocupacao
    analistas = horas / (capacidade_analista_dia * passos)

    turnos = _distribuicao_por_turno(dominio, prioridade, data)

    return {
        "data": data.date().isoformat(),
        "prioridade": prioridade,
        "horizonte": horizonte,
        "selo": r["situacao"]["selo"],
        "parametros": {"jornada_h": jornada_h, "ocupacao": ocupacao,
                       "fator_esforco": fator_esforco,
                       "capacidade_analista_dia_h": round(capacidade_analista_dia, 2)},
        "entrada": {
            "incidentes_previstos": incidentes,
            "banda": r["banda"],
            "dias_cobertos": passos,
            "duracao_mediana_h": round(duracao, 3),
            "janela_da_mediana_dias": cfg.JANELA_TAXA_DIAS,
        },
        "dimensionamento": {
            "horas_totais": round(horas, 1),
            "horas_por_dia": round(horas / passos, 1),
            "analistas_por_dia": round(analistas, 1),
            "analistas_por_dia_pior_caso": round(
                r["banda"]["superior"] * duracao * fator_esforco
                / (capacidade_analista_dia * passos), 1),
        },
        "por_turno": [
            {**t, "analistas": round(analistas * t["share"], 1),
             "horas": round(horas * t["share"], 1)}
            for t in turnos
        ],
        "avisos": avisos,
    }


def _duracao_mediana(dominio, prioridade, data):
    """Mediana das medianas diárias na janela recente, só na fatia tratada por humano."""
    f = dominio.fato
    inicio = data - pd.Timedelta(days=cfg.JANELA_TAXA_DIAS - 1)
    janela = f[(f.prioridade == prioridade) & (f.tipo_tratamento == GRUPO)
               & (f.data.between(inicio, data))]
    valores = janela.duracao_mediana_h.dropna()
    valores = valores[np.isfinite(valores)]
    return float(valores.median()) if len(valores) else None


def _distribuicao_por_turno(dominio, prioridade, data):
    """Share histórico de abertura por turno, na janela recente — como espalhar o quadro no dia."""
    t = dominio.turno
    inicio = data - pd.Timedelta(days=cfg.JANELA_TAXA_DIAS - 1)
    janela = t[(t.prioridade == prioridade) & (t.tipo_tratamento == GRUPO)
               & (t.data.between(inicio, data))]
    if janela.empty:
        return [{"turno": nome, "share": 1 / len(cfg.TURNOS), "abertos_no_periodo": 0}
                for nome in cfg.TURNOS]

    soma = janela.groupby("turno").abertos.sum()
    total = float(soma.sum())
    return [
        {"turno": nome,
         "share": round(float(soma.get(nome, 0)) / total, 4) if total else 0.0,
         "abertos_no_periodo": int(soma.get(nome, 0))}
        for nome in cfg.TURNOS
    ]
