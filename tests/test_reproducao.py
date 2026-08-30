"""Portão de qualidade: a API tem de servir o MESMO modelo que o notebook mediu.

Se este teste passa, `g_previsoes.csv` é reproduzível a partir dos artefatos de `models/` — ou
seja, o container responde exatamente o que a avaliação de §8 do notebook avaliou. Se falha, algo
na montagem da série, na fatia de histórico ou nas exógenas divergiu, e nenhum painel acima disso
tem sentido.

A tolerância é 0,01 porque `g_previsoes.csv` guarda os valores arredondados em 2 casas.
"""

import pandas as pd
import pytest

from api import config as cfg
from api import dominio as dom
from api import previsao as prev

TOLERANCIA = 0.011


@pytest.fixture(scope="module")
def contexto():
    dominio = dom.obter_dominio()
    return dominio, prev.Modelos(dominio)


def test_carrega_os_18_artefatos(contexto):
    _, modelos = contexto
    assert len(modelos) == 18, "o manifesto deveria descrever 18 artefatos"


def test_manifesto_cobre_todo_o_grao(contexto):
    _, modelos = contexto
    for grupo in cfg.GRUPOS:
        for p in cfg.PRIORIDADES:
            for h in cfg.HORIZONTES:
                assert modelos.meta(grupo, p, h)["modelo"] in ("ARIMA", "SARIMA")


@pytest.mark.parametrize("grupo", cfg.GRUPOS)
@pytest.mark.parametrize("prioridade", cfg.PRIORIDADES)
@pytest.mark.parametrize("horizonte", list(cfg.HORIZONTES))
def test_reproduz_previsoes_gold(contexto, grupo, prioridade, horizonte):
    """Replay de TODAS as origens de teste da combinação, contra a linha do modelo escolhido."""
    dominio, modelos = contexto
    meta = modelos.meta(grupo, prioridade, horizonte)

    g = dominio.previsoes_gold
    esperado = g[(g.tipo_tratamento == grupo) & (g.prioridade == prioridade)
                 & (g.horizonte == horizonte) & (g.modelo == meta["modelo"])
                 & (g.escolhido)]
    assert not esperado.empty, f"g_previsoes sem linhas escolhidas para {grupo} P{prioridade} {horizonte}"

    passos = cfg.HORIZONTES[horizonte]
    divergencias = []
    for _, linha in esperado.iterrows():
        # No D+1 a coluna `data` da gold é o dia PREVISTO; no D+7 é o dia de ORIGEM.
        origem = linha.data - pd.Timedelta(days=passos) if horizonte == "D+1" else linha.data

        r = prev.prever(dominio, modelos, grupo, prioridade, horizonte, origem)
        assert r["situacao"]["selo"] == cfg.SELO_TESTE, (
            f"{grupo} P{prioridade} {horizonte} origem {origem:%Y-%m-%d}: a gold diz que é teste, "
            f"a API classificou como {r['situacao']['selo']}"
        )
        assert not r["usou_fallback"], f"fallback acionado em {origem:%Y-%m-%d}"

        if abs(r["previsao"] - linha.valor_previsto) > TOLERANCIA:
            divergencias.append((origem.date(), r["previsao"], linha.valor_previsto))
        assert abs(r["real"] - linha.valor_real) < 1e-6, (
            f"{origem:%Y-%m-%d}: real da API {r['real']} != gold {linha.valor_real}"
        )

    assert not divergencias, (
        f"{grupo} P{prioridade} {horizonte}: {len(divergencias)} de {len(esperado)} origens "
        f"divergem. Primeiras: {divergencias[:3]}"
    )


def test_soma7_reproduz_alvo_da_silver(contexto):
    """`soma7.shift(-7)` tem de ser o `y_abertos_acum_1a7` já validado na exploração."""
    dominio, _ = contexto
    for (grupo, p), s in dominio.series.items():
        if grupo == "total":
            continue           # não existe na silver: é construído em `_agregar_total`
        ref = dominio.fato[(dominio.fato.tipo_tratamento == grupo)
                           & (dominio.fato.prioridade == p)][["data", "y_abertos_acum_1a7"]]
        j = s[["data", "y_acum_1a7"]].merge(ref, on="data", how="inner").dropna()
        assert (j.y_acum_1a7 - j.y_abertos_acum_1a7).abs().max() < 1e-6, (
            f"{grupo} P{p}: a série agregada não reproduz o alvo de D+7 da silver"
        )


def test_total_e_a_soma_das_duas_fatias(contexto):
    """O grupo `total` tem de ser exatamente `com_intervencao + sem_intervencao` em `abertos`."""
    dominio, _ = contexto
    for p in cfg.PRIORIDADES:
        com = dominio.serie("com_intervencao", p)[["data", "abertos"]]
        sem = dominio.serie("sem_intervencao", p)[["data", "abertos"]]
        tot = dominio.serie("total", p)[["data", "abertos"]]
        j = (com.merge(sem, on="data", suffixes=("_com", "_sem"))
             .merge(tot.rename(columns={"abertos": "abertos_total"}), on="data"))
        assert (j.abertos_com + j.abertos_sem - j.abertos_total).abs().max() < 1e-9
