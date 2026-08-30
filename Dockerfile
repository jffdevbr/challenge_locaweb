# Imagem autocontida: leva o código E o dado, porque nada do que a API precisa está versionado
# (todas as CSVs das camadas e todos os .pkl estão no .gitignore). Quem recebe a imagem roda sem
# preparar pasta nenhuma. Para desenvolvimento, o compose.yml sobrepõe estes caminhos com bind
# mounts — ver README_API.md.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CAMINHO_MODELOS=/app/models \
    CAMINHO_SILVER=/app/2_silver_data \
    CAMINHO_GOLD=/app/3_gold_data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/

# --- Dado (~19 MB) -------------------------------------------------------------------------
# Só o que a API lê. Nada de 0_raw_data, 1_bronze_data, notebooks ou .venv — ver .dockerignore.
COPY models/ ./models/
COPY 2_silver_data/s_fato_diario_prioridade.csv \
     2_silver_data/s_fato_diario_prioridade_turno.csv \
     2_silver_data/s_dim_calendario.csv \
     2_silver_data/s_fato_ola_prioridade.csv \
     ./2_silver_data/
COPY 3_gold_data/g_previsoes.csv \
     3_gold_data/g_avaliacao_modelos.csv \
     ./3_gold_data/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
