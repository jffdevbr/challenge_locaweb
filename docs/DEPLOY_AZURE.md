# Deploy na Azure — passo a passo executado

Registro do que foi rodado de verdade para publicar a API na Azure (Resource Group → ACR → Log
Analytics/Application Insights → ACI), na assinatura **"Azure for Students"** (tenant FIAP). É o
mesmo procedimento automatizado em [`azure/provisionar.sh`](../azure/provisionar.sh) — este
documento é a evidência passo a passo, com os problemas reais encontrados no caminho (todos em
ambiente **Windows + Git Bash**) e como foram resolvidos. Serve de base para a seção 2 do PDF de
entrega (evidência de provisionamento).

Nomes e valores usados nesta execução (região `brazilsouth`, sufixo `563445` = RM do grupo):

| Recurso | Nome |
|---|---|
| Resource Group | `rg-locaweb-previsao` |
| Azure Container Registry | `acrlocaweb563445` |
| Imagem | `lw-previsao:1.0` |
| Log Analytics Workspace | `log-locaweb-563445` |
| Application Insights | `appi-locaweb-563445` |
| Azure Container Instances | `aci-locaweb-previsao` |
| URL pública final | `http://locaweb-previsao-563445.brazilsouth.azurecontainer.io:8000` |

---

## 0) Login

```bash
az login --tenant 11dbbfe2-89b8-4549-be10-cec364e59551
az account show   # confirma "Azure for Students" como assinatura ativa
```

O token de uma sessão anterior tinha expirado no meio do trabalho (`AADSTS50173`) — precisou
refazer o login interativo antes de continuar.

---

## 1) Resource Group

```bash
az group create --name rg-locaweb-previsao --location brazilsouth --output table
```

---

## 2) Azure Container Registry + build da imagem

```bash
az acr create --resource-group rg-locaweb-previsao --name acrlocaweb563445 --sku Basic --output table
export PYTHONIOENCODING=utf-8
az acr build --registry acrlocaweb563445 --image lw-previsao:1.0 --file Dockerfile .
```

`az acr build` builda o `Dockerfile` da raiz **direto no ACR** — sobe o contexto local (repo
inteiro, menos o que o `.dockerignore` exclui) e builda remotamente, sem precisar de Docker
instalado na máquina.

**Problema real:** a primeira tentativa (sem `PYTHONIOENCODING=utf-8`) derrubou o cliente `az` no
meio do streaming do log de build:

```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 2509-2548
```

Isso é só o console do Windows (codepage `cp1252`) travando ao imprimir um caractere do log — o
build **em si** continuou e terminou no lado do servidor. Confirmado depois:

```bash
az acr task list-runs --registry acrlocaweb563445 --top 3 -o table
# RUN ID    STATUS     DURATION
# cq1       Succeeded  00:01:11
```

Reexecutar com `PYTHONIOENCODING=utf-8` (mesma causa-raiz do aviso já documentado em
`CLAUDE.md` para ler notebook no Windows) evita o crash do cliente numa próxima vez.

---

## 3) Log Analytics Workspace + Application Insights

```bash
az monitor log-analytics workspace create \
    --resource-group rg-locaweb-previsao \
    --workspace-name log-locaweb-563445 \
    --location brazilsouth --output table

WORKSPACE_ID=$(az monitor log-analytics workspace show \
    --resource-group rg-locaweb-previsao --workspace-name log-locaweb-563445 \
    --query customerId -o tsv)
WORKSPACE_CHAVE=$(az monitor log-analytics workspace get-shared-keys \
    --resource-group rg-locaweb-previsao --workspace-name log-locaweb-563445 \
    --query primarySharedKey -o tsv)
WORKSPACE_RESOURCE_ID=$(az monitor log-analytics workspace show \
    --resource-group rg-locaweb-previsao --workspace-name log-locaweb-563445 \
    --query id -o tsv)

az extension add --name application-insights --yes   # ver "problema real" abaixo

export MSYS_NO_PATHCONV=1                             # idem
az monitor app-insights component create \
    --resource-group rg-locaweb-previsao \
    --app appi-locaweb-563445 \
    --location brazilsouth \
    --kind web --application-type web \
    --workspace "$WORKSPACE_RESOURCE_ID" --output table

APPI_CONNECTION_STRING=$(az monitor app-insights component show \
    --resource-group rg-locaweb-previsao --app appi-locaweb-563445 \
    --query connectionString -o tsv)
```

**Dois problemas reais aqui:**

1. `az monitor app-insights component create` usa uma extensão da CLI (`application-insights`)
   que não vem instalada por padrão. Sem instalar antes, o comando pergunta interativamente
   "instalar agora? (Y/n)" — e quebra com `EOFError: EOF when reading a line` em qualquer execução
   não-interativa (como via ferramenta/CI). Resolvido com `az extension add --name
   application-insights --yes` antes de chamar o comando.
2. **Git Bash reescreve argumentos que começam com `/`** como se fossem caminho de arquivo do
   Windows — `$WORKSPACE_RESOURCE_ID` (que começa com `/subscriptions/...`) virava
   `C:/Program Files/Git/subscriptions/...` e o Azure devolvia `BadRequest: Could not retrieve the
   Log Analytics workspace from ARM`. Resolvido com `export MSYS_NO_PATHCONV=1` antes do comando —
   sem efeito em bash de verdade (Linux/macOS/WSL), só existe no Git Bash do Windows.

### Telemetria não aparecia na UI — dois bugs por trás do silêncio

Depois do primeiro deploy, `/health` e `/api/previsao` respondiam normalmente, mas nada aparecia
em **Application Insights → Logs** nem em **Live Metrics**, sem nenhum erro óbvio. Dois problemas
distintos, achados nessa ordem:

1. **`azure-monitor-opentelemetry-exporter` (pacote do exportador, versionado à parte) recusa um
   redirecionamento legítimo entre dois domínios da própria Azure Monitor.** O log do container
   mostrava `Refusing cross-origin redirect to https://brazilsouth-1.in.applicationinsights.azure.com.`
   — o Live Metrics fala primeiro com um endpoint global e é redirecionado pro regional; a
   checagem de segurança do SDK (contra um `Location` header malicioso) exige que origem e destino
   tenham exatamente o mesmo sufixo de domínio, e o par legítimo
   `*.services.visualstudio.com → *.applicationinsights.azure.com` não bate nessa regra —
   descartando a telemetria inteira, em silêncio, sem lançar exceção. Confirmado comparando o
   código-fonte de várias versões do pacote (baixadas com `pip download --no-deps`): o bug entrou
   entre a `1.0.0b50` e a `1.0.0b53`, e segue presente na última (`1.0.0b56`, a mesma que
   `azure-monitor-opentelemetry==1.6.4` resolve por padrão). Corrigido fixando a versão do
   exportador em `requirements_api_container.txt`:
   ```
   azure-monitor-opentelemetry==1.6.4
   azure-monitor-opentelemetry-exporter==1.0.0b50
   ```
2. **Mesmo sem o bug acima, nenhuma requisição HTTP virava telemetria** — só chamadas manuais ao
   tracer funcionavam (confirmado reproduzindo o envio localmente com `AzureMonitorTraceExporter`
   direto, fora do container: a Azure aceitava — `Transmission succeeded: Items accepted`).
   Causa: `opentelemetry-instrumentation-fastapi` instrumenta trocando a classe `fastapi.FastAPI`
   por uma versão instrumentada (`fastapi.FastAPI = _InstrumentedFastAPI`) — só pega **apps
   criados depois** dessa troca. Em `api/main.py`, `app = FastAPI(...)` já existia (via
   `from fastapi import FastAPI`, que fixa o nome no import) antes de `configure_azure_monitor()`
   rodar, então o `app` real nunca foi trocado pela versão instrumentada — nenhum request virava
   span. Corrigido chamando `FastAPIInstrumentor.instrument_app(app)` explicitamente logo depois
   de `configure_azure_monitor()`, instrumentando o objeto `app` já existente em vez de depender
   da troca de classe.

Depois dos dois fixes, rebuild + recriação do ACI, e `AppRequests` no Log Analytics passou a
mostrar cada chamada real (200/404/422) com `Success` certo, poucos segundos depois da chamada.

---

## 4) Credenciais do ACR

```bash
az acr update --name acrlocaweb563445 --admin-enabled true --output table
ACR_SERVIDOR=$(az acr show --name acrlocaweb563445 --query loginServer -o tsv)
ACR_USUARIO=$(az acr credential show --name acrlocaweb563445 --query username -o tsv)
ACR_SENHA=$(az acr credential show --name acrlocaweb563445 --query 'passwords[0].value' -o tsv)
```

---

## 5) Azure Container Instances

```bash
az container create \
    --resource-group rg-locaweb-previsao \
    --name aci-locaweb-previsao \
    --image "${ACR_SERVIDOR}/lw-previsao:1.0" \
    --registry-login-server "$ACR_SERVIDOR" \
    --registry-username "$ACR_USUARIO" \
    --registry-password "$ACR_SENHA" \
    --cpu 1 --memory 1.5 \
    --ports 8000 \
    --dns-name-label locaweb-previsao-563445 \
    --os-type Linux \
    --restart-policy OnFailure \
    --environment-variables APPLICATIONINSIGHTS_CONNECTION_STRING="$APPI_CONNECTION_STRING" \
    --log-analytics-workspace "$WORKSPACE_ID" \
    --log-analytics-workspace-key "$WORKSPACE_CHAVE" \
    --output table
```

**Problema real (evitável):** a primeira tentativa falhou com
`the --name/-n argument is required` porque a variável `ACI_NOME` só existia como default dentro
do script `provisionar.sh` — rodando os comandos "soltos" (não pelo script), ela não estava
definida em lugar nenhum. O mesmo já tinha acontecido com `IMAGEM` no passo 2. Corrigido
exportando os dois antes do comando. Quem rodar `azure/provisionar.sh` de ponta a ponta não sofre
esse problema — o script já define os defaults.

**Resultado:**

```bash
az container show --resource-group rg-locaweb-previsao --name aci-locaweb-previsao \
    --query ipAddress.fqdn -o tsv
# locaweb-previsao-563445.brazilsouth.azurecontainer.io

curl http://locaweb-previsao-563445.brazilsouth.azurecontainer.io:8000/health
# {"status":"ok","modelos_carregados":18,"series_montadas":9, ...}

curl "http://locaweb-previsao-563445.brazilsouth.azurecontainer.io:8000/api/previsao?data=2025-12-15&prioridade=3&horizonte=D%2B7"
# {"data":"2025-12-15","prioridade":3,"horizonte":"D+7", ...}
```

---

## Desligar tudo

```bash
bash azure/limpar.sh
```

Apaga o Resource Group inteiro (ACR, ACI, Log Analytics, Application Insights) — importante numa
assinatura de estudante, para não consumir crédito depois de entregue a atividade.
