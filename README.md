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

O produto final é uma API REST com duas páginas web. O **painel** (`/`) mostra os números
principais de um dia entre 01/09 e 31/12/2025: com e sem intervenção empilhados, com o D+1 sobre
os últimos 14 dias e o D+7 sobre as últimas 4 semanas, e a chance de quebra dos KPIs de OLA. Os **detalhes** (`/detalhe`) recebem *data + prioridade +
horizonte* e devolvem a previsão dos três grupos, mais três painéis de negócio: risco de
cumprimento de OLA, dimensionamento de capacidade e detecção de dias atípicos.

---

## O resultado, sem maquiagem

A decisão do modelo passou a ser por **série** (`grupo × prioridade × horizonte`, 18 no total), não
mais por `grupo × horizonte` agregado — escolher no agregado deixava a série de maior volume
decidir sozinha por todo o grupo. **11 das 18 séries superam o baseline ingênuo**; no critério
agregado anterior isso seria 2 de 6:

| Grupo | Horizonte | MAE agregado (3 prioridades) | MAE ingênuo | Ganho agregado |
|---|---|---|---|---|
| `com_intervencao` | D+1 | **14,70** | 15,87 | ✅ **+7,4 %** |
| `com_intervencao` | D+7 | **63,84** | 91,90 | ✅ **+30,5 %** |
| `sem_intervencao` | D+1 | 56,33 | **54,13** | ❌ −4,1 % |
| `sem_intervencao` | D+7 | 548,97 | **458,86** | ❌ −19,6 % |
| `total` | D+1 | 59,62 | **59,21** | ❌ −0,7 % |
| `total` | D+7 | 521,75 | **462,97** | ❌ −12,7 % |

Recomendação registrada: usar em produção apenas o modelo que supera o ingênuo na sua série —
hoje, 11 das 18 — e a própria regra ingênua como referência operacional nas outras 7,
concentradas em P3 de `sem_intervencao`/`total`, cujo nível salta dentro da própria janela de
teste (limitação de dado, não de modelo). O detalhamento por série está em
[`3_gold_data/data_dictionary.md`](3_gold_data/data_dictionary.md) e em
[`docs/CONTRATO_MODELOS.md`](docs/CONTRATO_MODELOS.md) §8.

A página de detalhes e a API mostram esse fato ao lado de cada previsão. O painel principal é a
única exceção, por decisão da autora: ele mostra o número do modelo sem a marca de ingênuo e
aponta para os detalhes (ver `docs/CONTRATO_MODELOS.md` §8).

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
        │  notebooks/model_training.ipynb       SARIMAX · ETS · Theta disputam por backtest de
        │                                       origem móvel; Prophet · LSTM · XGBoost, referência
        ▼
   3_gold_data/ (4 tabelas)  +  models/ (18 artefatos .pkl/.json + manifesto.csv)
        │
        │  api/     FastAPI + painel (/) e detalhes (/detalhe) — serve SARIMAX, ETS e Theta
        │           refiltrando o estado até a origem (docs/CONTRATO_MODELOS.md §7)
        ▼
   http://localhost:8000
```

Os três grupos × três prioridades × dois horizontes dão os **18 artefatos** de `models/`, cada
série com o seu próprio vencedor: **8 `SARIMAX`, 7 `Theta`, 3 `ETS`** nesta safra — os três disputam
por um backtest de origem móvel dentro do treino, nunca pelo MAE do teste. Nenhum Prophet e nenhum
LSTM foi escolhido; as duas famílias competem só como referência medida no hold-out, fora da
disputa (retreiná-las sob a mesma validação seria caro demais para o que renderam nas safras
anteriores). `ETS` e `Theta` vão para `models/` em `.json` — não são `SARIMAXResults` — e são
servidos pelo caminho descrito em `docs/CONTRATO_MODELOS.md` §7, implementado em
`api/previsao.py`.

### Estrutura de pastas

| Pasta | Conteúdo |
|---|---|
| `0_raw_data/` | CSV bruto da extração |
| `1_bronze_data/` | `b_incidentes.csv` (pasta Spark), grão do incidente |
| `2_silver_data/` | 17 fatos e dimensões diários |
| `3_gold_data/` | previsões e avaliação dos modelos |
| `models/` | 18 artefatos dos vencedores (`.pkl` SARIMAX, `.json` ETS/Theta) + `manifesto.csv` |
| `notebooks/` | os 3 notebooks do pipeline |
| `notebooks/testes/` | versões antigas, **fora do fluxo** — histórico, não reproduzir |
| `api/` | FastAPI (`main.py`, `previsao.py`, `ola.py`, `capacidade.py`, `atipicos.py`) + `web/` |
| `tests/` | portão de qualidade da reprodução |
| `docs/` | contrato dos modelos e manual da API |

---

## ⚠️ Nada de dado está versionado

O `.gitignore` exclui **todas** as CSVs das camadas 0–3, todos os `.pkl` e (desde que `ETS`/`Theta`
passaram a exportar em JSON) todo `models/*.json`. Quem clona este repositório recebe só código e
documentação — nenhuma tabela, nenhum modelo.

| Ausente no clone | Tamanho | Quem produz |
|---|---|---|
| `0_raw_data/LW-DATASET-CSV.CSV` | 23 MB | **ninguém — é o dataset original da Locaweb, você precisa tê-lo em mãos** |
| `1_bronze_data/b_incidentes.csv/` | 27 MB | `notebooks/data_validation.ipynb` |
| `2_silver_data/*.csv` (17 tabelas) | 13 MB | `notebooks/data_exploration.ipynb` |
| `3_gold_data/*.csv` (4 tabelas) | 220 KB | `notebooks/model_training.ipynb` |
| `models/` (18 artefatos + 18 sidecars `.config.json` + manifesto) | 22 MB | `notebooks/model_training.ipynb` |

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
  cobre os templates já vistos e os inéditos viram um aviso, não um erro.

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

Monta as 9 séries, aplica o split treino × teste com embargo, ajusta `SARIMAX`/`ETS`/`Theta` sob
um backtest de origem móvel (Prophet/LSTM/XGBoost entram só como referência), escolhe o vencedor
de cada **série** (`grupo × prioridade × horizonte`) e exporta (§12.4) as 4 tabelas de
`3_gold_data/` e os 18 artefatos de `models/`.

> **Nunca abrir este notebook com uma leitura de arquivo inteiro** — ele tem 3,7 MB. Para procurar
> algo dentro dele, iterar as células com `json.load` filtrando pelo termo.

### 5. Conferir a reprodução

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
```

É o portão de qualidade: `test_reproducao.py` replica as 18 combinações a partir de `models/` e
compara com `3_gold_data/g_previsoes.csv` (divergência máxima aceita: o arredondamento do próprio
arquivo). `test_classificacao.py` cobre os selos de data nas fronteiras e `test_ola.py`, as regras
de OLA; `test_painel.py` cobre a rota do painel (intervalo de datas, pilha com + sem, etiqueta de
período e virada do ano).

Na safra atual o teste reproduz as 534 origens de teste das 18 séries, nas três famílias.

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
| [`models/manifesto.csv`](models/manifesto.csv) | qual linha de `g_avaliacao_modelos` justifica cada artefato (`familia`, `transformacao`, `exog`, `mae`, `mase`, `mae_ingenuo`, `ganho_vs_ingenuo`, `supera_ingenuo`, `corte_teste`, `configuracao`) |

---

## Ressalvas conhecidas

Estão listadas aqui porque aparecem na tela e na resposta da API, e não devem ser descobertas por
acidente:

- **7 das 18 séries perdem para o baseline ingênuo** (tabela no topo). A página de detalhes marca
  `✅ supera o ingênuo` / `❌ perde do ingênuo` ao lado de cada previsão, e a API devolve o fato
  em `avisos`. O painel principal não mostra a marca, por decisão da autora.
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
