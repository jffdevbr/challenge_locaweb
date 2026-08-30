"""Os selos de situação da data, nas fronteiras exatas.

É o requisito central da tela: quem olha a previsão precisa saber se aquele dia esteve no treino,
no teste, no embargo entre os dois, ou depois do dado que existe. As fronteiras são as datas em
que o selo vira, e são elas que este teste fixa.
"""

import pandas as pd
import pytest

from api import config as cfg
from api import dominio as dom


@pytest.fixture(scope="module")
def dominio():
    return dom.obter_dominio()


def selo(dominio, grupo, data, horizonte, prioridade=3):
    return dom.classificar(dominio, grupo, prioridade, pd.Timestamp(data), horizonte)["selo"]


# -- com_intervencao: corte 2025-11-20, janela a partir de 2025-01-01 ---------------------------

@pytest.mark.parametrize("data,horizonte,esperado", [
    # D+1: o alvo é o dia seguinte, então não existe embargo.
    ("2025-11-18", "D+1", cfg.SELO_TREINO),      # alvo 19/11, ainda treino
    ("2025-11-19", "D+1", cfg.SELO_TESTE),       # alvo 20/11 = primeiro dia de teste
    ("2025-12-31", "D+1", cfg.SELO_SEM_RESPOSTA),  # alvo 01/01/2026, fora da série
    # D+7: a janela-alvo de 7 dias cria as 6 origens de embargo antes do corte.
    ("2025-11-12", "D+7", cfg.SELO_TREINO),      # alvo até 19/11, ainda treino
    ("2025-11-13", "D+7", cfg.SELO_EMBARGO),     # alvo até 20/11, invade o teste
    ("2025-11-18", "D+7", cfg.SELO_EMBARGO),     # última origem de embargo
    ("2025-11-19", "D+7", cfg.SELO_TESTE),       # alvo começa em 20/11
    ("2025-12-24", "D+7", cfg.SELO_TESTE),       # alvo até 31/12, o último com real
    ("2025-12-25", "D+7", cfg.SELO_SEM_RESPOSTA),  # alvo passaria de 31/12
])
def test_fronteiras_com_intervencao(dominio, data, horizonte, esperado):
    assert selo(dominio, "com_intervencao", data, horizonte) == esperado


# -- sem_intervencao / total: corte 2025-12-04, janela a partir de 2025-09-01 -------------------

@pytest.mark.parametrize("grupo", ["sem_intervencao", "total"])
@pytest.mark.parametrize("data,horizonte,esperado", [
    ("2025-08-31", "D+1", cfg.SELO_FORA_DA_JANELA),
    ("2025-09-01", "D+1", cfg.SELO_TREINO),
    ("2025-12-02", "D+1", cfg.SELO_TREINO),
    ("2025-12-03", "D+1", cfg.SELO_TESTE),
    ("2025-11-26", "D+7", cfg.SELO_TREINO),
    ("2025-11-27", "D+7", cfg.SELO_EMBARGO),
    ("2025-12-02", "D+7", cfg.SELO_EMBARGO),
    ("2025-12-03", "D+7", cfg.SELO_TESTE),
])
def test_fronteiras_grupos_curtos(dominio, grupo, data, horizonte, esperado):
    assert selo(dominio, grupo, data, horizonte) == esperado


def test_o_embargo_do_d7_tem_exatamente_6_origens(dominio):
    """O embargo é a janela de 7 dias batendo na fronteira: descarta `passos - 1` origens."""
    for grupo in cfg.GRUPOS:
        for p in cfg.PRIORIDADES:
            s = dominio.serie(grupo, p)
            selos = [dom.classificar(dominio, grupo, p, d, "D+7")["selo"]
                     for d in s.data[s.na_janela]]
            assert selos.count(cfg.SELO_EMBARGO) == cfg.PASSO_MAXIMO - 1, (
                f"{grupo} P{p}: {selos.count(cfg.SELO_EMBARGO)} origens de embargo, "
                f"esperado {cfg.PASSO_MAXIMO - 1}"
            )
            assert selos.count(cfg.SELO_EMBARGO) == 6


def test_d1_nao_tem_embargo(dominio):
    """No D+1 o alvo é um dia só: ou cabe no treino, ou já é teste."""
    for grupo in cfg.GRUPOS:
        s = dominio.serie(grupo, 3)
        selos = {dom.classificar(dominio, grupo, 3, d, "D+1")["selo"]
                 for d in s.data[s.na_janela]}
        assert cfg.SELO_EMBARGO not in selos


def test_fora_do_historico(dominio):
    assert selo(dominio, "com_intervencao", "2022-12-31", "D+1") == cfg.SELO_SEM_FEATURES
    assert selo(dominio, "com_intervencao", "2026-01-01", "D+1") == cfg.SELO_SEM_FEATURES


def test_regime_r1_recebe_texto_proprio(dominio):
    """Antes de 2025 o dado é artefato de extração — o aviso tem de dizer isso, não só
    'fora da janela'."""
    r = dom.classificar(dominio, "com_intervencao", 3, pd.Timestamp("2024-06-15"), "D+1")
    assert r["selo"] == cfg.SELO_FORA_DA_JANELA
    assert r["extrapolacao"] is True
    assert "R1" in r["explicacao"]


def test_quebra_de_setembro_recebe_texto_proprio(dominio):
    """Para sem_intervencao, uma data de 2025 anterior a setembro está antes da quebra."""
    r = dom.classificar(dominio, "sem_intervencao", 3, pd.Timestamp("2025-05-10"), "D+1")
    assert r["selo"] == cfg.SELO_FORA_DA_JANELA
    assert "monitoramento automático" in r["explicacao"]


def test_contagem_de_origens_de_teste_bate_com_a_gold(dominio):
    """Quantas origens de teste cada corte tem — o mesmo número que `g_previsoes` cobre."""
    esperado = {("com_intervencao", "D+1"): 42, ("com_intervencao", "D+7"): 36,
                ("sem_intervencao", "D+1"): 28, ("sem_intervencao", "D+7"): 22,
                ("total", "D+1"): 28, ("total", "D+7"): 22}
    for (grupo, horizonte), n in esperado.items():
        s = dominio.serie(grupo, 3)
        selos = [dom.classificar(dominio, grupo, 3, d, horizonte)["selo"]
                 for d in s.data[s.na_janela]]
        assert selos.count(cfg.SELO_TESTE) == n, f"{grupo} {horizonte}"
