#!/usr/bin/env bash
# Desliga tudo que `provisionar.sh` criou, num só comando: apagar o Resource Group apaga em
# cascata o ACR, o Log Analytics, o Application Insights e o ACI. Importante numa assinatura de
# estudante — evita consumir o crédito depois que a atividade foi entregue.
#
#   bash azure/limpar.sh

set -euo pipefail

SUFIXO="${SUFIXO:-563445}"
GRUPO_RECURSOS="${GRUPO_RECURSOS:-rg-locaweb-previsao}"

echo "Isso vai apagar o Resource Group '${GRUPO_RECURSOS}' e TODOS os recursos dentro dele."
read -r -p "Confirma? (digite 'apagar' para prosseguir) " confirmacao
if [ "$confirmacao" != "apagar" ]; then
    echo "Cancelado."
    exit 0
fi

az group delete --name "$GRUPO_RECURSOS" --yes --no-wait
echo "Exclusão disparada (--no-wait) — acompanhe com: az group show --name ${GRUPO_RECURSOS}"
