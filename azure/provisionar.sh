#!/usr/bin/env bash
# Provisionamento na Azure do serving de previsão de incidentes — Resource Group, Azure Container
# Registry (ACR), Log Analytics + Application Insights e Azure Container Instances (ACI) rodando
# a imagem já pronta (Dockerfile na raiz do projeto).
#
# Como rodar, a partir da raiz do repositório — o `az acr build` do PASSO 2 sobe o contexto de
# build local, e ele só tem os CSVs das camadas e os artefatos de models/ (.pkl SARIMAX, .json
# ETS/Theta e sidecars) se você rodou os notebooks antes (nada de dado está versionado — ver
# CLAUDE.md):
#
#   cd challenge_locaweb
#   bash azure/provisionar.sh
#
# O script é dividido em passos numerados e para entre eles (Enter para continuar) — para rodar
# sem pausa (ex.: CI), exporte PAUSAR=0. Idempotente: reexecutar não duplica recurso, `az ... create`
# atualiza no lugar quando o recurso já existe.

set -euo pipefail

# Git Bash (Windows) reescreve qualquer argumento que comece com "/" como se fosse um caminho de
# arquivo local (ex.: "/subscriptions/..." vira "C:/Program Files/Git/subscriptions/...") — quebra
# os `--workspace <resource-id>` abaixo. Sem efeito em bash "de verdade" (Linux/macOS/WSL).
export MSYS_NO_PATHCONV=1
# Sem isso, `az acr build` derruba o cliente (não o build em si) ao imprimir um caractere Unicode
# do log num console Windows em cp1252 — mesma causa-raiz do aviso de leitura de notebook no
# CLAUDE.md.
export PYTHONIOENCODING=utf-8

# --- Parâmetros (todos com default) --------------------------------------------------------------
LOCAL="${LOCAL:-brazilsouth}"
SUFIXO="${SUFIXO:-563445}"                          # RM do grupo — garante nome único de ACR
GRUPO_RECURSOS="${GRUPO_RECURSOS:-rg-locaweb-previsao}"
ACR_NOME="${ACR_NOME:-acrlocaweb${SUFIXO}}"
IMAGEM="${IMAGEM:-lw-previsao:1.0}"
LOG_WORKSPACE="${LOG_WORKSPACE:-log-locaweb-${SUFIXO}}"
APP_INSIGHTS="${APP_INSIGHTS:-appi-locaweb-${SUFIXO}}"
ACI_NOME="${ACI_NOME:-aci-locaweb-previsao}"
ACI_DNS_LABEL="${ACI_DNS_LABEL:-locaweb-previsao-${SUFIXO}}"
PAUSAR="${PAUSAR:-1}"

passo() {
    echo
    echo "=================================================================================="
    echo "PASSO $1"
    echo "=================================================================================="
    if [ "$PAUSAR" = "1" ]; then
        read -r -p "Enter para continuar (Ctrl+C para interromper)... " _
    fi
}

# --- PASSO 1 — Resource Group --------------------------------------------------------------------
passo "1/5 — Resource Group"
az group create --name "$GRUPO_RECURSOS" --location "$LOCAL" --output table

# --- PASSO 2 — Azure Container Registry + build da imagem ----------------------------------------
# `az acr build` builda o Dockerfile da raiz DIRETO no ACR — sem precisar de Docker instalado
# localmente (item "?? Importante" do enunciado). Sobe o contexto de build inteiro (menos o que o
# .dockerignore exclui), então precisa rodar da raiz do repo com o dado das camadas já gerado.
passo "2/5 — ACR + build da imagem (leva alguns minutos)"
az acr create --resource-group "$GRUPO_RECURSOS" --name "$ACR_NOME" --sku Basic --output table
az acr build --registry "$ACR_NOME" --image "$IMAGEM" --file Dockerfile .

# --- PASSO 3 — Log Analytics + Application Insights -----------------------------------------------
passo "3/5 — Log Analytics + Application Insights"
# A extensão da CLI não vem instalada por padrão; sem isso o comando abaixo pergunta
# interativamente "instalar agora?" e quebra em execução não-interativa.
az extension add --name application-insights --yes --only-show-errors >/dev/null 2>&1 || true

az monitor log-analytics workspace create \
    --resource-group "$GRUPO_RECURSOS" \
    --workspace-name "$LOG_WORKSPACE" \
    --location "$LOCAL" \
    --output table

WORKSPACE_ID="$(az monitor log-analytics workspace show \
    --resource-group "$GRUPO_RECURSOS" --workspace-name "$LOG_WORKSPACE" \
    --query customerId -o tsv)"
WORKSPACE_CHAVE="$(az monitor log-analytics workspace get-shared-keys \
    --resource-group "$GRUPO_RECURSOS" --workspace-name "$LOG_WORKSPACE" \
    --query primarySharedKey -o tsv)"
WORKSPACE_RESOURCE_ID="$(az monitor log-analytics workspace show \
    --resource-group "$GRUPO_RECURSOS" --workspace-name "$LOG_WORKSPACE" \
    --query id -o tsv)"

az monitor app-insights component create \
    --resource-group "$GRUPO_RECURSOS" \
    --app "$APP_INSIGHTS" \
    --location "$LOCAL" \
    --kind web \
    --application-type web \
    --workspace "$WORKSPACE_RESOURCE_ID" \
    --output table

APPI_CONNECTION_STRING="$(az monitor app-insights component show \
    --resource-group "$GRUPO_RECURSOS" --app "$APP_INSIGHTS" \
    --query connectionString -o tsv)"

# --- PASSO 4 — Credenciais do ACR --------------------------------------------------------------
passo "4/5 — Credenciais do ACR (para o ACI puxar a imagem)"
az acr update --name "$ACR_NOME" --admin-enabled true --output table
ACR_SERVIDOR="$(az acr show --name "$ACR_NOME" --query loginServer -o tsv)"
ACR_USUARIO="$(az acr credential show --name "$ACR_NOME" --query username -o tsv)"
ACR_SENHA="$(az acr credential show --name "$ACR_NOME" --query 'passwords[0].value' -o tsv)"

# --- PASSO 5 — Azure Container Instances ---------------------------------------------------------
passo "5/5 — Azure Container Instances (sobe a API)"
az container create \
    --resource-group "$GRUPO_RECURSOS" \
    --name "$ACI_NOME" \
    --image "${ACR_SERVIDOR}/${IMAGEM}" \
    --registry-login-server "$ACR_SERVIDOR" \
    --registry-username "$ACR_USUARIO" \
    --registry-password "$ACR_SENHA" \
    --cpu 1 --memory 1.5 \
    --ports 8000 \
    --dns-name-label "$ACI_DNS_LABEL" \
    --os-type Linux \
    --restart-policy OnFailure \
    --environment-variables APPLICATIONINSIGHTS_CONNECTION_STRING="$APPI_CONNECTION_STRING" \
    --log-analytics-workspace "$WORKSPACE_ID" \
    --log-analytics-workspace-key "$WORKSPACE_CHAVE" \
    --output table

FQDN="$(az container show --resource-group "$GRUPO_RECURSOS" --name "$ACI_NOME" \
    --query ipAddress.fqdn -o tsv)"

echo
echo "=================================================================================="
echo "PRONTO"
echo "=================================================================================="
echo "Painel:           http://${FQDN}:8000/            (ex.: /?data=2025-12-20)"
echo "Detalhes:         http://${FQDN}:8000/detalhe"
echo "Docs (OpenAPI):   http://${FQDN}:8000/docs"
echo "Health:           http://${FQDN}:8000/health"
echo "Resource Group:   ${GRUPO_RECURSOS}"
echo
echo "Teste rápido:"
echo "  curl http://${FQDN}:8000/health"
echo "  curl \"http://${FQDN}:8000/api/painel?origem=2025-12-20\""
echo "  curl \"http://${FQDN}:8000/api/previsao?data=2025-12-15&prioridade=3&horizonte=D%2B7\""
echo
echo "Para desligar tudo (evitar consumo de crédito): bash azure/limpar.sh"
