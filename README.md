# Previsão de incidentes — Challenge Locaweb

Previsão diária do volume de incidentes **P2, P3 e P4** em dois horizontes — **D+1** (o dia
seguinte) e **D+7** (o acumulado dos próximos sete dias) — separando os incidentes que exigiram
trabalho humano dos que fecharam sozinhos no monitoramento automático.

Essa separação é a decisão de desenho central do projeto. São dois fenômenos diferentes dentro da
mesma série:

| Grupo | O que é | Por que separar |
|---|---|---|
| `com_intervencao` | alguém trabalhou no incidente | é o que consome analista e sustenta dimensionamento de capacidade |
| `sem_intervencao` | abriu e fechou no monitoramento automático | volume alto, comportamento próprio, quebra estrutural em setembro/2025 |
| `total` | a soma das duas fatias | **construído**, não é uma terceira categoria do dado |

O produto final é uma API REST com página web que recebe *data + prioridade + horizonte* e devolve
a previsão dos três grupos, mais três painéis de negócio: risco de cumprimento de OLA,
dimensionamento de capacidade e detecção de dias atípicos.

---

## O resultado, sem maquiagem

**1 de 6 cortes supera o baseline ingênuo.** Isso está medido, documentado, exposto na tela ao lado
de cada previsão e não é suavizado em lugar nenhum do projeto:

| Grupo | Horizonte | Vencedor | MAE | MAE ingênuo | Supera o ingênuo? |
|---|---|---|---|---|---|
| `com_intervencao` | D+1 | SARIMA | 16,21 | 15,87 | ❌ −2,2 % |
| `com_intervencao` | D+7 | ARIMA | **58,20** | 91,90 | ✅ **+36,7 %** |
| `sem_intervencao` | D+1 | ARIMA | 85,83 | 54,13 | ❌ −58,6 % |
| `sem_intervencao` | D+7 | ARIMA | 563,14 | 458,86 | ❌ −22,7 % |
| `total` | D+1 | ARIMA | 82,21 | 59,21 | ❌ −38,8 % |
| `total` | D+7 | ARIMA | 555,80 | 462,97 | ❌ −20,1 % |

Recomendação registrada: usar o modelo em produção onde ele ganha — hoje, `com_intervencao` em
D+7 — e a própria regra ingênua como referência operacional nos demais. O detalhamento está em
[`3_gold_data/data_dictionary.md`](3_gold_data/data_dictionary.md) e em
[`docs/CONTRATO_MODELOS.md`](docs/CONTRATO_MODELOS.md) §8.

---

## Arquitetura

Pipeline em camadas, cada seta é um notebook:

```
   0_raw_data/LW-DATASET-CSV.CSV          ← dataset original da Locaweb (você precisa tê-lo)
        │
        │  notebooks/data_validation.ipynb      PySpark: PK e duplicatas, domínios permitidos,
        │                                       regras de negócio, nulos
        ▼
   1_bronze_data/b_incidentes.csv         grão: 1 linha por incidente (122.543 × 23)
        │                                 ⚠️ é uma PASTA de partições Spark, ISO-8859-1
        │
        │  notebooks/data_exploration.ipynb     enriquecimento, calendário, OLA, rotulagem de
        │                                       templates por LLM, quebras estruturais
        ▼
   2_silver_data/  (17 tabelas)           fatos diários e dimensões
        │                                 s_fato_diario_prioridade.csv é a base de tudo
        │
        │  notebooks/model_training.ipynb       ARIMA · SARIMA · Prophet · LSTM · XGBoost,
        │                                       split com embargo, escolha do vencedor
        ▼
   3_gold_data/ (4 tabelas)  +  models/ (18 .pkl + manifesto.csv)
        │
        │  api/     FastAPI + página web — serving por apply(refit=False) + forecast
        ▼
   http://localhost:8000
```

Os três grupos × três prioridades × dois horizontes dão os **18 artefatos** de `models/`. Todos são
`SARIMAXResults` do statsmodels: nesta safra nenhum Prophet e nenhum LSTM sobreviveu à escolha — e
é por isso que o container de serving não precisa de `torch` nem de `prophet`.

### Estrutura de pastas

| Pasta | Conteúdo |
|---|---|
| `0_raw_data/` | CSV bruto da extração |
| `1_bronze_data/` | `b_incidentes.csv` (pasta Spark), grão do incidente |
| `2_silver_data/` | 17 fatos e dimensões diários |
| `3_gold_data/` | previsões e avaliação dos modelos |
| `models/` | 18 `.pkl` dos vencedores + `manifesto.csv` |
| `notebooks/` | os 3 notebooks do pipeline |
| `notebooks/testes/` | versões antigas, **fora do fluxo** — histórico, não reproduzir |
| `api/` | FastAPI (`main.py`, `previsao.py`, `ola.py`, `capacidade.py`, `atipicos.py`) + `web/` |
| `tests/` | portão de qualidade da reprodução |
| `docs/` | contrato dos modelos e manual da API |

---

## ⚠️ Nada de dado está versionado

O `.gitignore` exclui **todas** as CSVs das camadas 0–3 e **todos** os `.pkl`. Quem clona este
repositório recebe só código e documentação — nenhuma tabela, nenhum modelo.

| Ausente no clone | Tamanho | Quem produz |
|---|---|---|
| `0_raw_data/LW-DATASET-CSV.CSV` | 23 MB | **ninguém — é o dataset original da Locaweb, você precisa tê-lo em mãos** |
| `1_bronze_data/b_incidentes.csv/` | 27 MB | `notebooks/data_validation.ipynb` |
| `2_silver_data/*.csv` (17 tabelas) | 13 MB | `notebooks/data_exploration.ipynb` |
| `3_gold_data/*.csv` (4 tabelas) | 220 KB | `notebooks/model_training.ipynb` |
| `models/*.pkl` (18 artefatos) | 17 MB | `notebooks/model_training.ipynb` |

**Sem o CSV original não há como reproduzir nada** — nem os notebooks nem a API. A imagem Docker
também não resolve isso sozinha: ela é montada a partir do dado gerado localmente
(veja `Dockerfile` e `.dockerignore`), então quem constrói a imagem precisa antes ter rodado o
pipeline. Um `git clone && docker build` em máquina limpa **não funciona**, e isso é por desenho,
não por descuido.

Consequências práticas: não sugerir `git add` de dado ou de modelo; qualquer entrega executável
precisa levar o dado junto.

---

## Pré-requisitos

- **Python 3.12.10.** O projeto já tem um ambiente em `./.venv/` — usar `./.venv/Scripts/python.exe`
  e não criar um venv novo.
- **Java 17+ no `PATH`** (com `JAVA_HOME`), apenas para o `data_validation.ipynb`, que roda em
  PySpark. Os outros dois notebooks e a API não precisam de Java.
- **Docker** (opcional), para subir a API em container.
- **Chave da API Anthropic** (opcional), só para o `data_exploration.ipynb`: a rotulagem de
  templates por LLM (§2.9). Crie `notebooks/.env` com

  ```
  MINHA_CHAVE_API_CLAUDE=sk-ant-...
  ```

  Sem a chave o notebook **roda até o fim assim mesmo**: o cache de rótulos em `s_dim_template.csv`
  cobre os templates já vistos e os inéditos viram um aviso, não um erro. Atenção ao espaço antes
  do `=`: `MINHA_CHAVE_API_CLAUDE = valor` cria uma variável chamada `"MINHA_CHAVE_API_CLAUDE "` e o
  `getenv` devolve `None`.

Os três notebooks detectam sozinhos se estão no Google Colab ou na máquina local (`IN_COLAB`).
Localmente, os caminhos são **relativos à pasta `notebooks/`** (`../0_raw_data/`, `../2_silver_data/`),
então o kernel precisa estar com o diretório de trabalho em `notebooks/`.

---

## Rodar de ponta a ponta

### 0. Instalar o ambiente

```bash
git clone <este-repositorio>
cd challenge_locaweb
./.venv/Scripts/python.exe -m pip install -r requirements_notebooks.txt
```

Existem **dois** arquivos de dependências, e eles não são intercambiáveis:

| Arquivo | Para quê |
|---|---|
| `requirements_notebooks.txt` | rodar os 3 notebooks — inclui Spark, Prophet, torch, XGBoost, LLM |
| `requirements_api_container.txt` | ambiente mínimo de serving, o que vai para dentro da imagem |

As versões de `numpy`, `pandas`, `scipy` e `statsmodels` são idênticas nos dois **de propósito**: os
artefatos são pickle de statsmodels e a versão que desserializa precisa casar com a que serializou.

### 1. Colocar o dataset original

```
0_raw_data/LW-DATASET-CSV.CSV
```

O nome é literal — é o que `data_validation.ipynb` procura.

### 2. `notebooks/data_validation.ipynb` → camada bronze

Precisa de Java. Valida chave primária, domínios, regras de negócio (categoria × subcategoria,
duração, flags de KPI, pai × filho, status) e nulos, e grava a partição Spark em
`1_bronze_data/b_incidentes.csv/`.

### 3. `notebooks/data_exploration.ipynb` → camada silver

É o notebook mais longo. Enriquece o grão do incidente, monta o calendário determinístico, deriva
os fatos diários e as dimensões, calcula o atingimento de OLA e faz a análise exploratória
(quebras estruturais, sazonalidade, concentração). Grava as 17 tabelas em `2_silver_data/`.

### 4. `notebooks/model_training.ipynb` → camada gold + modelos

Monta as 9 séries, aplica o split treino × teste com embargo, treina e compara ARIMA, SARIMA,
Prophet, LSTM e XGBoost, escolhe o vencedor de cada `grupo × horizonte` e exporta (§12.4) as 4
tabelas de `3_gold_data/` e os 18 `.pkl` de `models/`.

> **Nunca abrir este notebook com uma leitura de arquivo inteiro** — ele tem 3,7 MB. Para procurar
> algo dentro dele, iterar as células com `json.load` filtrando pelo termo.

### 5. Conferir a reprodução

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
```

É o portão de qualidade: `test_reproducao.py` replica as 18 combinações a partir dos `.pkl` e
compara com `3_gold_data/g_previsoes.csv` (divergência máxima aceita: o arredondamento do próprio
arquivo). `test_classificacao.py` cobre os selos de data nas fronteiras e `test_ola.py`, as regras
de OLA.

### 6. Subir a API

```bash
docker compose up --build          # desenvolvimento: dado montado como somente-leitura
```

ou, para a imagem autocontida de entrega (o dado vai *dentro* da imagem):

```bash
docker build -t lw-previsao:1.0 .
docker run --rm -p 8000:8000 lw-previsao:1.0
```

Sem container:

```bash
./.venv/Scripts/python.exe -m pip install -r requirements_api_container.txt
./.venv/Scripts/python.exe -m uvicorn api.main:app --reload
```

Abre em **http://localhost:8000**, com o OpenAPI interativo em `/docs`. Rotas, selos de data,
painéis e exemplos de `curl`: [`docs/README_API.md`](docs/README_API.md).

---

## Convenções de arquivo

**Camadas silver e gold:** CSV, `sep=";"`, `encoding="utf-8-sig"`, sem índice, datas como string
ISO `YYYY-MM-DD` (sem hora, sem fuso). Ler sempre com:

```python
pd.read_csv(caminho, sep=";", parse_dates=["data"])
```

**Camada bronze é diferente:** é uma pasta de partições Spark, `sep=";"`, `encoding="ISO-8859-1"`,
datas em UTC com sufixo `Z`. A leitura de referência está no dicionário da camada.

Toda tabela nova passa pelo `salvar()`/`CATALOGO` do notebook que a produz — a chave declarada
precisa existir, ser única e não ter nulo — e o `data_dictionary.md` da camada é atualizado junto.

Tabelas mais usadas:

- `2_silver_data/s_fato_diario_prioridade.csv` — grão `data × prioridade × tipo_tratamento`,
  53 colunas, 2023-01-02 a 2025-12-31. É a base de tudo.
- `2_silver_data/s_dim_calendario.csv` — calendário determinístico, o único que vai além do fim dos
  dados (cobre 2026, para as exógenas futuras).
- `2_silver_data/s_fato_ola_prioridade.csv` — grão `data × prioridade`, atingimento de OLA.
- `3_gold_data/g_previsoes.csv` — previsão de todos os modelos no teste, contra o real.
- `3_gold_data/g_avaliacao_modelos.csv` — MAE/MASE/piso ingênuo por corte, e quem foi escolhido.

---

## Documentação especializada

Este README é a porta de entrada. O detalhe vive nos documentos abaixo, que são mantidos junto com
o código que descrevem:

| Documento | Para quê |
|---|---|
| [`docs/CONTRATO_MODELOS.md`](docs/CONTRATO_MODELOS.md) | **fonte da verdade do serving**: o que são os 18 artefatos, os dois horizontes, exógenas, montagem das séries, janelas, cortes, embargo e o código de previsão. Ler antes de mexer em `api/`. |
| [`docs/README_API.md`](docs/README_API.md) | subir a API e o container, rotas, como o dado entra na imagem, os selos de situação da data, os três painéis e os testes |
| [`1_bronze_data/data_dictionary.md`](1_bronze_data/data_dictionary.md) | grão do incidente: 23 colunas, cobertura temporal, sentinelas nulas, flags de validação |
| [`2_silver_data/data_dictionary.md`](2_silver_data/data_dictionary.md) | as 17 tabelas silver, coluna a coluna, com as convenções de `regime` e `tipo_tratamento` |
| [`3_gold_data/data_dictionary.md`](3_gold_data/data_dictionary.md) | desenho do treino, estudo de features, resultados e ressalvas — sem maquiagem |
| [`models/manifesto.csv`](models/manifesto.csv) | qual linha de `g_avaliacao_modelos` justifica cada `.pkl` (`mae`, `mase`, `mae_ingenuo`, `ganho_vs_ingenuo`, `supera_ingenuo`, `corte_teste`, `configuracao`) |

---

## Ressalvas conhecidas

Estão listadas aqui porque aparecem na tela e na resposta da API, e não devem ser descobertas por
acidente:

- **5 dos 6 cortes perdem para o baseline ingênuo** (tabela no topo). A tela marca
  `✅ supera o ingênuo` / `❌ perde do ingênuo` ao lado de cada previsão.
- **As faixas de OLA por volume estão estouradas.** Em 31/12/2025 a P2 fechou 15.649 contra um corte
  máximo de 6.337, e a P3 fechou 41.732 contra 24.277 — o atingimento é 0 % o ano inteiro. As faixas
  foram calibradas para outra escala e precisam de recalibração. A regra de **duração** é a que
  está viva.
- **P4 não tem meta de OLA** em nenhuma das duas regras. O painel diz isso; não inventa número.
- **O painel de capacidade depende de calibração da área.** `duracao_mediana_h` é tempo decorrido até
  o fechamento, não esforço em mãos — por isso `fator_esforco` é parâmetro da rota, e o número só
  vira dimensionamento depois que a área calibrar esse fator uma vez.
- **Só a primeira perna da projeção de OLA vem de modelo**; o resto é extrapolação de taxa diária,
  e está rotulado como tal.
