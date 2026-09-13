"""API de previsão de incidentes — rotas, validação e a página web.

Toda resposta carrega um bloco `avisos`. As ressalvas do projeto (modelo que perde para o
ingênuo, faixa de OLA estourada, P4 sem meta, extrapolação fora da janela) não podem viver só no
HTML: quem consumir a API por outro caminho precisa recebê-las junto com o número.
"""

import logging
import os
import platform
from contextlib import asynccontextmanager
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd
import statsmodels
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import atipicos as mod_atipicos
from api import capacidade as mod_capacidade
from api import config as cfg
from api import dominio as dom
from api import ola as mod_ola
from api import previsao as prev

logger = logging.getLogger("api.main")

DOMINIO = None
MODELOS = None


@asynccontextmanager
async def ciclo_de_vida(_app):
    """Tabelas e artefatos carregam uma vez, no startup. Requisição não lê disco.

    Um artefato faltando ou com contagem de exógenas divergente derruba a subida — é o lugar
    certo para esse erro aparecer, e não no meio de uma demonstração.
    """
    global DOMINIO, MODELOS
    DOMINIO = dom.obter_dominio()
    MODELOS = prev.obter_modelos()
    yield


app = FastAPI(
    title="Previsão de incidentes — Locaweb",
    description="Serving dos modelos vencedores (D+1 e D+7) com leitura de risco de OLA, "
                "capacidade e dias atípicos.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)

# Application Insights — só instrumenta se a connection string vier por ambiente (deploy na
# Azure). Local, sem a variável, o bloco abaixo não roda; ver `azure/provisionar.sh`.
#
# `configure_azure_monitor()` instrumenta FastAPI trocando a classe `fastapi.FastAPI` por uma
# versão instrumentada — só pega apps criados DEPOIS dessa troca. Como `app` já existe (linha
# acima, via `from fastapi import FastAPI`, que fixou o nome no import), essa troca automática
# não alcança o nosso `app`: precisa do `FastAPIInstrumentor.instrument_app(app)` explícito.
if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    configure_azure_monitor(logger_name="api")
    FastAPIInstrumentor.instrument_app(app)
    logger.info("Application Insights instrumentado (com FastAPI).")


# ==================================================================================================
# Validação de entrada
# ==================================================================================================

def _validar_data(texto):
    try:
        return pd.Timestamp(date.fromisoformat(texto))
    except ValueError:
        raise HTTPException(422, f"data inválida: {texto!r} — use o formato AAAA-MM-DD")


def _validar_prioridade(p):
    if p not in cfg.PRIORIDADES:
        raise HTTPException(422, f"prioridade {p} fora de escopo — use 2, 3 ou 4")
    return p


def _validar_horizonte(h):
    if h not in cfg.HORIZONTES:
        raise HTTPException(422, f"horizonte {h!r} inválido — use 'D+1' ou 'D+7'")
    return h


# ==================================================================================================
# Rotas de diagnóstico e catálogo
# ==================================================================================================

@app.get("/health", tags=["diagnóstico"])
def health():
    """Estado da carga e versões — é onde uma incompatibilidade de pickle aparece como
    diagnóstico em vez de erro 500 no meio de uma demonstração."""
    return {
        "status": "ok",
        "modelos_carregados": len(MODELOS),
        "series_montadas": len(DOMINIO.series),
        "historico": {"inicio": DOMINIO.data_min.date().isoformat(),
                      "fim": DOMINIO.data_max.date().isoformat()},
        "versoes": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "statsmodels": statsmodels.__version__,
        },
    }


@app.get("/api/catalogo", tags=["catálogo"])
def catalogo():
    """O que a tela precisa para montar os seletores, e o manifesto inteiro dos modelos."""
    return {
        "datas": {"minima": DOMINIO.data_min.date().isoformat(),
                  "maxima": DOMINIO.data_max.date().isoformat()},
        "prioridades": cfg.PRIORIDADES,
        "horizontes": list(cfg.HORIZONTES),
        "grupos": cfg.GRUPOS,
        "janelas": {
            g: {**cfg.JANELA[g],
                "fim_treino": (pd.Timestamp(cfg.JANELA[g]["corte"])
                               - pd.Timedelta(days=1)).date().isoformat()}
            for g in cfg.GRUPOS
        },
        "regimes": {
            "R1": {"ate": "2024-12-31", "descricao": "artefato de extração — fora da modelagem"},
            "R2": {"de": cfg.INICIO_R2, "ate": "2025-08-31", "descricao": "pré-automação"},
            "R3": {"de": cfg.INICIO_R3, "descricao": "pós-automação"},
        },
        "selos": [cfg.SELO_TREINO, cfg.SELO_EMBARGO, cfg.SELO_TESTE,
                  cfg.SELO_SEM_RESPOSTA, cfg.SELO_FORA_DA_JANELA, cfg.SELO_SEM_FEATURES],
        "manifesto": DOMINIO.manifesto.to_dict(orient="records"),
    }


@app.get("/api/features", tags=["entradas"])
def features(data: str = Query(..., description="data de origem, AAAA-MM-DD"),
             prioridade: int = Query(..., description="2, 3 ou 4"),
             horizonte: str = Query("D+1", description="'D+1' ou 'D+7'")):
    """As features de entrada daquele dia, por grupo — o que o modelo lê e o que a tela mostra."""
    d = _validar_data(data)
    _validar_prioridade(prioridade)
    _validar_horizonte(horizonte)

    saida = {g: dom.features_do_dia(DOMINIO, g, prioridade, d,
                                    MODELOS.meta(g, prioridade, horizonte)["exog"])
             for g in cfg.GRUPOS}
    if all(v is None for v in saida.values()):
        raise HTTPException(404, f"{data} está fora do histórico disponível")
    return {"data": data, "prioridade": prioridade, "horizonte": horizonte, "grupos": saida}


# ==================================================================================================
# Rota principal
# ==================================================================================================

@app.get("/api/previsao", tags=["previsão"])
def previsao(data: str = Query(..., description="data de origem, AAAA-MM-DD"),
             prioridade: int = Query(...),
             horizonte: str = Query("D+7"),
             dias_grafico: int = Query(60, ge=7, le=365)):
    """Os três grupos lado a lado, mais a soma dos dois modelos por tipo.

    A comparação entre `soma dos 2 modelos` e `modelo único total` é a pergunta de desenho que
    `g_comparacao_grao` mediu e não conseguiu decidir — mostrar as duas leituras na tela é mais
    honesto do que escolher uma.
    """
    d = _validar_data(data)
    _validar_prioridade(prioridade)
    _validar_horizonte(horizonte)

    cards = {g: prev.prever(DOMINIO, MODELOS, g, prioridade, horizonte, d) for g in cfg.GRUPOS}
    if all(c["previsao"] is None for c in cards.values()):
        raise HTTPException(
            404, f"{data} está fora do histórico ({DOMINIO.data_min:%Y-%m-%d} a "
                 f"{DOMINIO.data_max:%Y-%m-%d}) — sem features, não há o que prever")

    return {
        "data": data,
        "prioridade": prioridade,
        "horizonte": horizonte,
        "entradas": dom.features_do_dia(DOMINIO, "total", prioridade, d,
                                        MODELOS.meta("total", prioridade, horizonte)["exog"]),
        "cards": cards,
        "soma_dos_dois": _soma_dos_dois(cards),
        "grafico": _serie_grafico(prioridade, horizonte, d, dias_grafico, cards),
        "avisos": _avisos_previsao(cards),
    }


def _soma_dos_dois(cards):
    """`previsto_com + previsto_sem` contra o real total — o outro lado de `g_comparacao_grao`."""
    com, sem, total = cards["com_intervencao"], cards["sem_intervencao"], cards["total"]
    if com["previsao"] is None or sem["previsao"] is None:
        return None

    previsto = com["previsao"] + sem["previsao"]
    real = None
    if com.get("real") is not None and sem.get("real") is not None:
        real = com["real"] + sem["real"]

    vantagem = None
    if real is not None and total["previsao"] is not None:
        erro_soma = abs(previsto - real)
        erro_unico = abs(total["previsao"] - real)
        vantagem = round((erro_unico - erro_soma) / erro_unico * 100, 1) if erro_unico else None

    return {
        "previsao": round(previsto, 2),
        "real": real,
        "erro": round(previsto - real, 2) if real is not None else None,
        "acuracia_pct": prev.acuracia(previsto, real),
        "vantagem_da_separacao_pct": vantagem,
        "nota": "positivo = separar por tipo errou menos que o modelo único nesta data",
    }


def _serie_grafico(prioridade, horizonte, data, dias, cards):
    """Histórico recente + o ponto previsto, por grupo, para o gráfico da tela."""
    coluna = cfg.COLUNA_SERIE[horizonte]
    saida = {}
    for g in cfg.GRUPOS:
        s = DOMINIO.serie(g, prioridade)
        i = DOMINIO.indice_da_data(g, prioridade, data)
        if i is None:
            continue
        fatia = s.iloc[max(0, i - dias + 1):i + 1]
        card = cards[g]
        saida[g] = {
            "historico": [{"data": t.date().isoformat(), "valor": _num(v)}
                          for t, v in zip(fatia.data, fatia[coluna])],
            "previsao": None if card["previsao"] is None else {
                "data": card["situacao"]["data_alvo"],
                "valor": card["previsao"],
                "inferior": card["banda"]["inferior"],
                "superior": card["banda"]["superior"],
                "real": card.get("real"),
            },
        }
    return {"coluna": coluna, "series": saida}


def _num(v):
    f = float(v)
    return None if not np.isfinite(f) else round(f, 2)


def _avisos_previsao(cards):
    avisos = []
    for g, c in cards.items():
        if c["previsao"] is None:
            continue
        sit = c["situacao"]
        if sit["selo"] in (cfg.SELO_FORA_DA_JANELA, cfg.SELO_TREINO, cfg.SELO_SEM_RESPOSTA,
                           cfg.SELO_EMBARGO):
            avisos.append({"grupo": g, "nivel": "atencao", "texto": sit["explicacao"]})
        if not c["desempenho_no_teste"]["supera_ingenuo"]:
            avisos.append({
                "grupo": g, "nivel": "critico",
                "texto": (f"O modelo {c['modelo']} deste corte NÃO supera o baseline ingênuo no "
                          f"teste ({c['desempenho_no_teste']['ganho_vs_ingenuo']:+.1f} % de MAE, "
                          f"regra '{c['desempenho_no_teste']['regra_ingenua']}'). Recomendação "
                          "registrada no projeto: usar o ingênuo como referência operacional "
                          "aqui."),
            })
        if c["usou_fallback"]:
            avisos.append({"grupo": g, "nivel": "critico",
                           "texto": "A projeção falhou e caiu no fallback (último valor "
                                    "observado). O número não é do modelo."})
    return avisos


# ==================================================================================================
# Painel principal
# ==================================================================================================

# Empilhados na tela: a pilha prevista é a soma dos dois modelos. O `total` fica em /detalhe.
GRUPOS_PAINEL = ["com_intervencao", "sem_intervencao"]


@app.get("/api/painel", tags=["painel"])
def painel_principal(origem: str = Query(..., description=f"data de origem, AAAA-MM-DD, de "
                                                          f"{cfg.PAINEL_INICIO} a {cfg.PAINEL_FIM}")):
    """Tudo o que o painel principal mostra numa origem, para as 3 prioridades.

    Com e sem intervenção vêm separados para a tela empilhar: o histórico diário e semanal, as
    previsões D+1 e D+7 de cada um, os KPIs de OLA e uma etiqueta dizendo em que período (treino,
    teste, produção) a data cai. O filtro de prioridade é feito no navegador; o resultado é
    memorizado por origem.

    O bloco `avisos` carrega, como em toda rota, as séries cujo modelo não supera o ingênuo no
    teste. A página principal escolhe não renderizá-lo; a página de detalhes renderiza.
    """
    d = _validar_data(origem)
    if not pd.Timestamp(cfg.PAINEL_INICIO) <= d <= pd.Timestamp(cfg.PAINEL_FIM):
        raise HTTPException(422, f"origem {origem} fora do painel — use de {cfg.PAINEL_INICIO} "
                                 f"a {cfg.PAINEL_FIM}")
    return _painel(d.date().isoformat())


@lru_cache(maxsize=256)
def _painel(origem):
    d = pd.Timestamp(origem)
    previsoes = {(g, p, h): prev.prever(DOMINIO, MODELOS, g, p, h, d)
                 for g in GRUPOS_PAINEL for p in cfg.PRIORIDADES for h in cfg.HORIZONTES}
    blocos = {p: _bloco_prioridade(p, d, previsoes) for p in cfg.PRIORIDADES}
    return {
        "origem": origem,
        "intervalo": {"inicio": cfg.PAINEL_INICIO, "fim": cfg.PAINEL_FIM},
        "situacao": _situacao_painel(previsoes),
        "prioridades": {**blocos, "todas": _bloco_agregado(blocos)},
        "kpis": {p: mod_ola.painel_kpis(DOMINIO, MODELOS, p, d) for p in cfg.PRIORIDADES},
        "avisos": _avisos_painel(previsoes),
    }


def _bloco_prioridade(p, d, previsoes):
    """Pilhas realizadas (diária e semanal) e as duas previsões empilhadas, de uma prioridade."""
    series = {g: DOMINIO.serie(g, p).set_index("data") for g in GRUPOS_PAINEL}

    def pilha(data, coluna):
        return {g.split("_")[0]: _num(series[g].at[data, coluna]) for g in GRUPOS_PAINEL}

    dias = pd.date_range(end=d, periods=cfg.PAINEL_DIAS_D1, freq="D")
    # Semanas fechando em D, D-7, D-14...: `soma7` de cada fim é a semana inteira realizada.
    fins = [d - pd.Timedelta(days=cfg.PASSO_MAXIMO * k)
            for k in range(cfg.PAINEL_SEMANAS_D7 - 1, -1, -1)]
    return {
        "diario": [{"data": t.date().isoformat(), **pilha(t, "abertos")} for t in dias],
        "semanal": [{"inicio": (t - pd.Timedelta(days=cfg.PASSO_MAXIMO - 1)).date().isoformat(),
                     "fim": t.date().isoformat(), **pilha(t, "soma7")} for t in fins],
        "d1": _previsao_empilhada(previsoes, p, "D+1", d),
        "d7": _previsao_empilhada(previsoes, p, "D+7", d),
    }


def _previsao_empilhada(previsoes, p, horizonte, d):
    partes = {g.split("_")[0]: previsoes[(g, p, horizonte)] for g in GRUPOS_PAINEL}
    reais = [r["real"] for r in partes.values()]
    return {
        "inicio": (d + pd.Timedelta(days=1)).date().isoformat(),
        "fim": (d + pd.Timedelta(days=cfg.HORIZONTES[horizonte])).date().isoformat(),
        "previsto": round(sum(r["previsao"] for r in partes.values()), 2),
        "real": None if None in reais else sum(reais),
        **{k: {"previsao": r["previsao"], "banda": r["banda"], "real": r["real"],
               "familia": r["familia"]}
           for k, r in partes.items()},
    }


def _somar(valores):
    return None if any(v is None for v in valores) else round(sum(valores), 2)


def _bloco_agregado(blocos):
    """A visão "todas as prioridades": a soma dos blocos de P2, P3 e P4.

    Não existe modelo para a prioridade inteira somada — a previsão agregada é a soma das seis
    previsões (2 tipos × 3 prioridades), do mesmo jeito que a pilha já soma com + sem. A faixa
    não entra: a faixa de uma soma não é a soma das faixas, e o bloco vem com `banda` nula em vez
    de um número inventado.
    """
    partes = list(blocos.values())

    def pilha(series, chaves):
        return [{**{k: pontos[0][k] for k in chaves},
                 "com": _somar([x["com"] for x in pontos]),
                 "sem": _somar([x["sem"] for x in pontos])}
                for pontos in zip(*series)]

    def previsao(h):
        blocos_h = [x[h] for x in partes]

        def tipo(g):
            return {"previsao": _somar([x[g]["previsao"] for x in blocos_h]), "banda": None,
                    "real": _somar([x[g]["real"] for x in blocos_h]), "familia": None}

        return {"inicio": blocos_h[0]["inicio"], "fim": blocos_h[0]["fim"],
                "previsto": _somar([x["previsto"] for x in blocos_h]),
                "real": _somar([x["real"] for x in blocos_h]),
                "com": tipo("com"), "sem": tipo("sem")}

    return {
        "diario": pilha([x["diario"] for x in partes], ["data"]),
        "semanal": pilha([x["semanal"] for x in partes], ["inicio", "fim"]),
        "d1": previsao("d1"),
        "d7": previsao("d7"),
    }


def _situacao_painel(previsoes):
    """Uma etiqueta para a data: em que período de treino/teste as quatro previsões caem.

    O selo depende do grupo e do horizonte, não da prioridade — basta olhar uma delas.
    """
    p = cfg.PRIORIDADES[0]
    selos = {(g, h): previsoes[(g, p, h)]["situacao"]["selo"]
             for g in GRUPOS_PAINEL for h in cfg.HORIZONTES}
    valores = set(selos.values())
    if valores == {cfg.SELO_SEM_RESPOSTA}:
        chave, texto = "produção", "ainda não existe real para comparar"
    elif valores <= {cfg.SELO_TESTE, cfg.SELO_SEM_RESPOSTA}:
        chave, texto = "teste", "o modelo nunca viu estes dias no ajuste"
    elif cfg.SELO_TREINO in valores:
        chave, texto = "treino", "o modelo viu estes dias no ajuste — o acerto aqui é otimista"
    else:
        chave, texto = "fronteira", "entre treino e teste — parte das previsões está no embargo"
    return {"chave": chave, "texto": texto,
            "detalhe": [{"grupo": g, "horizonte": h, "selo": s} for (g, h), s in selos.items()]}


def _avisos_painel(previsoes):
    avisos = []
    for (g, p, h), r in previsoes.items():
        if not r["desempenho_no_teste"]["supera_ingenuo"]:
            avisos.append({
                "grupo": g, "prioridade": p, "horizonte": h, "nivel": "critico",
                "texto": (f"{r['familia']} não supera o ingênuo no teste "
                          f"({r['desempenho_no_teste']['ganho_vs_ingenuo']:+.1f} % de MAE, "
                          f"regra '{r['desempenho_no_teste']['regra_ingenua']}')."),
            })
        if r["usou_fallback"]:
            avisos.append({"grupo": g, "prioridade": p, "horizonte": h, "nivel": "critico",
                           "texto": "A projeção caiu no fallback (último valor)."})
    return avisos


# ==================================================================================================
# Painéis de negócio
# ==================================================================================================

@app.get("/api/risco-ola", tags=["negócio"])
def risco_ola(data: str = Query(...),
              prioridade: int = Query(...),
              horizonte: str = Query("D+7"),
              ate: str = Query(None, description="fim da projeção; padrão = 31/12 do ano da data")):
    """Risco de queda do cumprimento de OLA, nas duas regras (duração e volume)."""
    d = _validar_data(data)
    _validar_prioridade(prioridade)
    _validar_horizonte(horizonte)
    fim = _validar_data(ate) if ate else pd.Timestamp(year=d.year, month=12, day=31)
    if fim < d:
        raise HTTPException(422, "o fim da projeção é anterior à data de origem")
    return mod_ola.painel(DOMINIO, MODELOS, prioridade, d, horizonte, fim)


@app.get("/api/capacidade", tags=["negócio"])
def capacidade(data: str = Query(...),
               prioridade: int = Query(...),
               horizonte: str = Query("D+7"),
               jornada_h: float = Query(cfg.JORNADA_H_PADRAO, gt=0, le=24),
               ocupacao: float = Query(cfg.OCUPACAO_PADRAO, gt=0, le=1),
               fator_esforco: float = Query(cfg.FATOR_ESFORCO_PADRAO, gt=0, le=10)):
    """Previsão de `com_intervencao` traduzida em horas e analistas, por turno."""
    d = _validar_data(data)
    _validar_prioridade(prioridade)
    _validar_horizonte(horizonte)
    return mod_capacidade.painel(DOMINIO, MODELOS, prioridade, d, horizonte,
                                 jornada_h, ocupacao, fator_esforco)


@app.get("/api/atipicos", tags=["negócio"])
def atipicos(inicio: str = Query(...),
             fim: str = Query(...),
             prioridade: int = Query(...),
             grupo: str = Query("com_intervencao"),
             alfa: float = Query(cfg.ALFA_BANDA_ALERTA, gt=0, lt=1)):
    """Dias em que o real caiu fora da banda de previsão — candidatos a evento sistêmico."""
    d0, d1 = _validar_data(inicio), _validar_data(fim)
    _validar_prioridade(prioridade)
    if grupo not in cfg.GRUPOS:
        raise HTTPException(422, f"grupo {grupo!r} inválido — use {cfg.GRUPOS}")
    if d1 < d0:
        raise HTTPException(422, "o fim do intervalo é anterior ao início")
    if (d1 - d0).days > 400:
        raise HTTPException(422, "intervalo acima de 400 dias — reduza a janela da varredura")
    return mod_atipicos.varrer(DOMINIO, MODELOS, grupo, prioridade, d0, d1, alfa)


# ==================================================================================================
# Página web
# ==================================================================================================

class EstaticosRevalidados(StaticFiles):
    """Estáticos com `Cache-Control: no-cache`: o navegador revalida a cada acesso.

    Sem o cabeçalho, o navegador decide sozinho por quanto tempo reaproveitar a cópia antiga — e
    depois de um deploy a página nova carregava o JS e o CSS do deploy anterior (estilo antigo e
    erro no botão "Todas"). Revalidar custa um 304 quando nada mudou, graças ao ETag.
    """

    def file_response(self, *args, **kwargs):
        resposta = super().file_response(*args, **kwargs)
        resposta.headers["Cache-Control"] = "no-cache"
        return resposta


SEM_CACHE = {"Cache-Control": "no-cache"}

app.mount("/static", EstaticosRevalidados(directory=cfg.CAMINHO_WEB), name="static")


@app.get("/", include_in_schema=False)
def pagina():
    """Painel principal — os números da virada do ano."""
    return FileResponse(cfg.CAMINHO_WEB / "index.html", headers=SEM_CACHE)


@app.get("/detalhe", include_in_schema=False)
def pagina_detalhe():
    """Página de detalhes — qualquer data, selos, ressalvas e os três painéis de negócio."""
    return FileResponse(cfg.CAMINHO_WEB / "detalhe.html", headers=SEM_CACHE)
