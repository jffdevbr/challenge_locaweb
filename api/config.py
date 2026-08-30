"""Constantes do serving — todas literais, copiadas do notebook de treino.

Nenhum valor aqui é recalculado em tempo de execução: janela, corte e faixa de OLA são decisões
de desenho tomadas no treino, e recalculá-las na API abriria a porta para a API e o notebook
discordarem em silêncio. Ver `docs/CONTRATO_MODELOS.md`.
"""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

CAMINHO_MODELOS = Path(os.environ.get("CAMINHO_MODELOS", RAIZ / "models"))
CAMINHO_SILVER = Path(os.environ.get("CAMINHO_SILVER", RAIZ / "2_silver_data"))
CAMINHO_GOLD = Path(os.environ.get("CAMINHO_GOLD", RAIZ / "3_gold_data"))
CAMINHO_WEB = Path(__file__).resolve().parent / "web"

# --- Grão --------------------------------------------------------------------------------------
PRIORIDADES = [2, 3, 4]
GRUPOS = ["com_intervencao", "sem_intervencao", "total"]
GRUPOS_DO_DADO = ["com_intervencao", "sem_intervencao"]   # `total` é construído, não vem do dado

HORIZONTES = {"D+1": 1, "D+7": 7}
COLUNA_SERIE = {"D+1": "abertos", "D+7": "soma7"}
PASSO_MAXIMO = 7

# --- Janela e corte, por grupo (§5 do contrato) -------------------------------------------------
JANELA = {
    "com_intervencao": {"inicio": "2025-01-01", "fim": "2025-12-31", "corte": "2025-11-20"},
    "sem_intervencao": {"inicio": "2025-09-01", "fim": "2025-12-31", "corte": "2025-12-04"},
    "total":           {"inicio": "2025-09-01", "fim": "2025-12-31", "corte": "2025-12-04"},
}

# Quebras de regime — o que torna uma data anterior à janela mais do que "fora do intervalo".
INICIO_R2 = "2025-01-01"   # fim do artefato de extração
INICIO_R3 = "2025-09-01"   # entrada do pipeline de monitoramento automático

# --- Exógenas de cada horizonte (só as famílias SARIMA recebem) ---------------------------------
EXOG_MODELO = {
    "D+1": ["feriado", "vespera_feriado", "pos_feriado"],
    "D+7": ["feriados_7d", "vesperas_7d"],
}

# --- Features mostradas na tela -----------------------------------------------------------------
FEATURES_CALENDARIO = [
    "dia_semana", "fim_de_semana", "dia_util", "feriado",
    "vespera_feriado", "pos_feriado", "dia_mes",
    "sen_semana", "cos_semana", "sen_ano", "cos_ano",
]
FEATURES_JANELA = ["feriados_7d", "dias_uteis_7d", "vesperas_7d", "feriados_j7", "dias_uteis_j7"]
FEATURES_EXOGENAS = [
    "inc_por_ic", "inc_por_descricao", "inc_por_time",
    "fechados", "backlog", "saldo_aberto_fechado",
    "abertos_sem_classificacao",
    "ics_distintos", "times_distintos", "descricoes_distintas",
]
# Razões do grupo `total`: numerador e denominador somados ANTES de dividir.
COMPONENTES_RAZAO = {
    "inc_por_ic": ("abertos", "ics_distintos"),
    "inc_por_descricao": ("abertos", "descricoes_distintas"),
    "inc_por_time": ("abertos", "times_distintos"),
}
# Colunas extras que a tela usa mas que não entram em modelo nenhum.
FEATURES_CONTEXTO = ["duracao_mediana_h", "duracao_p90_h", "taxa_monitoramento", "regime"]

JANELAS_CALENDARIO = [("feriado", "feriados"), ("dia_util", "dias_uteis"),
                      ("vespera_feriado", "vesperas")]

# --- Selos de situação da data (§2 do plano) ----------------------------------------------------
SELO_SEM_FEATURES = "SEM FEATURES"
SELO_FORA_DA_JANELA = "FORA DA JANELA"
SELO_TREINO = "TREINO"
SELO_EMBARGO = "EMBARGO"
SELO_TESTE = "TESTE"
SELO_SEM_RESPOSTA = "SEM RESPOSTA"

# --- Regras de OLA ------------------------------------------------------------------------------
# Calibradas sobre o acumulado ANUAL da prioridade inteira. P4 não tem faixa definida.
ESCALA_OLA = [150, 125, 100, 75, 50, 0]
FAIXAS_OLA_DURACAO = {2: [31, 36, 40, 46, 54], 3: [201, 231, 264, 291, 321]}
FAIXAS_OLA_VOLUME = {2: [4585, 5389, 6169, 6253, 6337], 3: [19489, 22117, 22525, 23893, 24277]}

JANELA_TAXA_DIAS = 28        # trailing usado para taxas de conversão e medianas
SORTEIOS_MONTE_CARLO = 2000

# --- Capacidade ---------------------------------------------------------------------------------
JORNADA_H_PADRAO = 8.0
OCUPACAO_PADRAO = 0.75
FATOR_ESFORCO_PADRAO = 1.0
TURNOS = ["madrugada", "manha", "tarde", "noite"]

# --- Detector de dia atípico --------------------------------------------------------------------
ALFA_BANDA_TELA = 0.20       # banda de 80 % mostrada na tela
ALFA_BANDA_ALERTA = 0.05     # banda de 95 % que define "atípico"
JANELA_MEDIANA_CONCENTRACAO = 90

# --- Paleta (mesma de model_training.ipynb célula 3) --------------------------------------------
PALETA = {
    "p2": "#C0392B", "p3": "#E67E22", "p4": "#F1C40F",
    "total": "#2C3E50", "neutro": "#95A5A6", "destaque": "#2980B9",
    "real": "#2C3E50", "treino": "#BDC3C7", "teste": "#E8DAEF",
}
