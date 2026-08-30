"""O motor de OLA tem de reproduzir a coluna que a silver já calculou.

Com projeção de zero dias, `atingimento()` sobre o acumulado do dia é, por construção, o mesmo
`atingimento_ola_duracao` / `atingimento_ola_volume` de `s_fato_ola_prioridade`. Se divergir, a
tabela de faixas copiada para `api/config.py` saiu de sincronia com a que gerou a silver — e o
painel inteiro passaria a mentir sem levantar exceção.
"""

import numpy as np
import pandas as pd
import pytest

from api import config as cfg
from api import dominio as dom
from api import ola
from api import previsao as prev


@pytest.fixture(scope="module")
def contexto():
    dominio = dom.obter_dominio()
    return dominio, prev.obter_modelos()


@pytest.mark.parametrize("regra,coluna_silver,faixas", [
    ("duracao", "atingimento_ola_duracao", cfg.FAIXAS_OLA_DURACAO),
    ("volume", "atingimento_ola_volume", cfg.FAIXAS_OLA_VOLUME),
])
def test_atingimento_reproduz_a_silver(contexto, regra, coluna_silver, faixas):
    dominio, _ = contexto
    spec = ola.REGRAS[regra]
    o = dominio.ola

    for p in cfg.PRIORIDADES:
        fatia = o[o.prioridade == p]
        cortes = faixas.get(p)
        if cortes is None:
            assert fatia[coluna_silver].isna().all(), (
                f"P{p} não tem faixa de {regra} definida, mas a silver traz valor"
            )
            continue
        calculado = np.array([ola.atingimento(v, cortes)
                              for v in fatia[spec["coluna_acumulada"]]])
        esperado = fatia[coluna_silver].to_numpy(dtype=float)
        assert np.allclose(calculado, esperado, equal_nan=True), (
            f"P{p}, regra de {regra}: o atingimento calculado divergiu da silver"
        )


def test_p4_nao_tem_meta(contexto):
    dominio, modelos = contexto
    r = ola.painel(dominio, modelos, 4, pd.Timestamp("2025-12-15"), "D+7",
                   pd.Timestamp("2025-12-31"))
    for regra in ("duracao", "volume"):
        assert r["regras"][regra]["tem_meta"] is False
    assert any("não tem faixa de OLA" in a["texto"] for a in r["avisos"])


def test_faixa_de_volume_estourada_e_sinalizada(contexto):
    """P2 e P3 passaram o corte máximo de volume — o painel tem de dizer, não desenhar medidor."""
    dominio, modelos = contexto
    for p in (2, 3):
        r = ola.painel(dominio, modelos, p, pd.Timestamp("2025-12-15"), "D+7",
                       pd.Timestamp("2025-12-31"))
        volume = r["regras"]["volume"]
        assert volume["faixa_estourada"] is True
        assert volume["atingimento_hoje_pct"] == 0.0
        assert any("corte máximo" in a["texto"] for a in r["avisos"])


def test_probabilidades_somam_um(contexto):
    dominio, modelos = contexto
    r = ola.painel(dominio, modelos, 3, pd.Timestamp("2025-11-15"), "D+7",
                   pd.Timestamp("2025-12-31"))
    dist = r["regras"]["duracao"]["distribuicao_de_faixas"]
    assert abs(sum(d["probabilidade"] for d in dist) - 1.0) < 0.01


def test_orcamento_e_o_que_falta_para_o_proximo_corte(contexto):
    """Em 15/12 a P3 tinha 189 violações e o próximo corte era 201: 12 de folga."""
    dominio, modelos = contexto
    r = ola.painel(dominio, modelos, 3, pd.Timestamp("2025-12-15"), "D+7",
                   pd.Timestamp("2025-12-31"))
    duracao = r["regras"]["duracao"]
    assert duracao["acumulado_hoje"] == 189.0
    assert duracao["atingimento_hoje_pct"] == 150.0
    assert duracao["proximo_corte"] == 201.0
    assert duracao["orcamento_restante"] == 12.0


def test_cenario_recente_alerta_a_escalada_de_dezembro(contexto):
    """O caso que dá razão ao painel.

    A P3 cruzou o corte 201 em 26/12/2025, caindo de 150 % para 125 %. Em 15/12 a taxa da janela
    de 28 dias ainda estava achatada pela calmaria de novembro e dava risco baixo; a taxa dos
    últimos 7 dias já mostrava a escalada. O cenário recente tem de projetar o cruzamento dentro
    do período — é ele que faria o alerta sair a tempo.
    """
    dominio, modelos = contexto
    r = ola.painel(dominio, modelos, 3, pd.Timestamp("2025-12-15"), "D+7",
                   pd.Timestamp("2025-12-31"))
    duracao = r["regras"]["duracao"]
    cenario = duracao["cenario_taxa_recente"]

    assert duracao["probabilidade_de_piorar"] < 0.20, "cenário base deveria estar tranquilo"
    assert cenario["probabilidade_de_piorar"] > 0.50, "cenário recente deveria alertar"
    assert cenario["tendencia"]["razao"] > 1.5
    assert cenario["data_provavel_de_cruzamento"]["dentro_da_projecao"] is True

    # A projeção pela taxa recente cai a até 3 dias do cruzamento real (26/12).
    projetado = pd.Timestamp(cenario["data_provavel_de_cruzamento"]["data"])
    assert abs((projetado - pd.Timestamp("2025-12-26")).days) <= 3

    assert any("achatando uma escalada" in a["texto"] for a in r["avisos"])


def test_projecao_de_zero_dias_nao_move_o_acumulado(contexto):
    """Sem dias para projetar, o esperado é o próprio acumulado de hoje."""
    dominio, modelos = contexto
    data = pd.Timestamp("2025-12-31")
    r = ola.painel(dominio, modelos, 3, data, "D+1", data)
    duracao = r["regras"]["duracao"]
    assert duracao["projecao"]["atingimento_esperado_pct"] == duracao["atingimento_hoje_pct"]
