"""O painel principal: intervalo de datas, pilha com + sem, etiqueta da data e a virada do ano.

A pilha prevista é a soma dos dois modelos por tipo — se a rota começasse a devolver outro número
no lugar (o modelo `total`, por exemplo), a tela passaria a mostrar uma soma que não bate com as
duas camadas desenhadas.
"""

import pytest
from fastapi.testclient import TestClient

from api import config as cfg
from api.main import app


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def painel(cliente, origem):
    r = cliente.get("/api/painel", params={"origem": origem})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("origem,esperado", [
    ("2025-08-31", 422),    # antes de 01/09: sem_intervencao só extrapolaria
    (cfg.PAINEL_INICIO, 200),
    (cfg.PAINEL_FIM, 200),
    ("2026-01-01", 422),
    ("31/12/2025", 422),
])
def test_intervalo_de_datas(cliente, origem, esperado):
    assert cliente.get("/api/painel", params={"origem": origem}).status_code == esperado


def test_pilha_prevista_e_a_soma_dos_dois_modelos(cliente):
    for p, b in painel(cliente, "2025-12-15")["prioridades"].items():
        for h in ("d1", "d7"):
            assert abs(b[h]["previsto"] - b[h]["com"]["previsao"] - b[h]["sem"]["previsao"]) < 0.011
        assert len(b["diario"]) == cfg.PAINEL_DIAS_D1
        assert len(b["semanal"]) == cfg.PAINEL_SEMANAS_D7


def test_semana_prevista_emenda_na_ultima_realizada(cliente):
    b = painel(cliente, "2025-12-15")["prioridades"]["3"]
    assert b["semanal"][-1]["fim"] == "2025-12-15"
    assert (b["d7"]["inicio"], b["d7"]["fim"]) == ("2025-12-16", "2025-12-22")
    assert b["diario"][-1]["data"] == "2025-12-15" and b["d1"]["inicio"] == "2025-12-16"


@pytest.mark.parametrize("origem,chave", [
    ("2025-10-15", "treino"),
    ("2025-12-10", "teste"),
    ("2025-12-31", "produção"),
])
def test_etiqueta_da_data(cliente, origem, chave):
    assert painel(cliente, origem)["situacao"]["chave"] == chave


def test_ano_novo_so_quando_a_semana_atravessa_a_virada(cliente):
    def duracao(origem):
        return painel(cliente, origem)["kpis"]["3"]["regras"]["duracao"]

    assert duracao("2025-12-24")["ano_novo"] is None       # D+7 termina em 31/12
    assert duracao("2025-12-26")["ano_novo"] is not None
    assert duracao("2025-12-31")["ano_corrente"]["fechado"] is True
