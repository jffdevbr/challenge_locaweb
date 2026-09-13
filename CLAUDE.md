# challenge_locaweb — guia para sessões de trabalho

Previsão diária de incidentes P2/P3/P4 (Locaweb), em D+1 e D+7, separando incidentes que
exigiram trabalho humano (`com_intervencao`) dos que fecharam sozinhos via monitoramento
automático (`sem_intervencao`).

## Regras rápidas

- **Ambiente:** `./.venv/Scripts/python.exe` (Python 3.12.10, Windows). Não criar venv novo.
- **Idioma:** todo código, comentário, docstring, coluna e texto de tela em **português**.
- **Guia de desenho:** *simples que funciona*. Onde o simples empata com o complexo, o simples vence.
- **Nunca ler notebook com `Read`** — `model_training.ipynb` tem 3,7 MB. Ver *Ler um notebook* abaixo.
- **Honestidade sobre resultado:** 7 das 18 séries têm vencedor que **perde para o baseline
  ingênuo** (11 superam). Isso está medido e documentado, e não pode ser suavizado nos
  documentos, na API (bloco `avisos` de toda rota) nem na página `/detalhe`. Única exceção,
  decidida pela autora em 2026-09-10: o painel principal (`/`) mostra sempre o número do modelo,
  sem a marca "perde do ingênuo" — e aponta para `/detalhe`, onde a marca continua.

## Camadas de dado

| Pasta | Conteúdo | Dicionário |
|---|---|---|
| `0_raw_data/` | CSV bruto da extração | — |
| `1_bronze_data/` | `b_incidentes.csv`, grão do incidente | `1_bronze_data/data_dictionary.md` |
| `2_silver_data/` | fatos e dimensões diários | `2_silver_data/data_dictionary.md` |
| `3_gold_data/` | previsões e avaliação dos modelos | `3_gold_data/data_dictionary.md` |
| `models/` | 18 vencedores (`.pkl` SARIMAX, `.json` ETS/Theta) + sidecars `.config.json` + `manifesto.csv` | `docs/CONTRATO_MODELOS.md` |
| `dashboard/` | relatório Power BI (`Dashboard_Challenge_Locaweb.pbix`), sobre a silver | `dashboard/DICIONARIO_DASHBOARD.md` |

Tabelas mais usadas:

- `2_silver_data/s_fato_diario_prioridade.csv` — grão `data × prioridade × tipo_tratamento`,
  53 colunas, 2023-01-02 a 2025-12-31. É a base de tudo.
- `2_silver_data/s_dim_calendario.csv` — calendário determinístico (feriados, ciclos seno/cosseno).
- `2_silver_data/s_fato_ola_prioridade.csv` — grão `data × prioridade`, atingimento de OLA.
- `3_gold_data/g_previsoes.csv` — previsão de todos os modelos no teste, contra o real.
- `3_gold_data/g_avaliacao_modelos.csv` — MAE/MASE/piso ingênuo por corte, e quem foi escolhido.

**Convenção de arquivo, em todas as camadas:** CSV, `sep=";"`, `encoding="utf-8-sig"`, sem índice,
datas como string ISO `YYYY-MM-DD` (sem hora, sem fuso). Ler sempre com
`pd.read_csv(..., sep=";", parse_dates=["data"])`.

**Contrato de escrita:** toda tabela nova passa por `salvar()`/`CATALOGO` do notebook que a produz
— a chave declarada precisa existir, ser única e não ter nulo. Ao criar tabela, atualizar o
`data_dictionary.md` da camada.

## ⚠️ Nada de dado está versionado

`.gitignore` exclui **todas** as CSVs das camadas 0–3, **todos** os `.pkl` e `models/*.json`. Quem clona o
repositório recebe só código e documentação. Consequências:

- não sugerir `git add` de dado ou de modelo;
- qualquer entrega executável precisa levar o dado junto (ver `api/` e o `Dockerfile`).

Exceção: `dashboard/*.pbix` **é versionado** — é relatório/artefato de análise, não dado bruto nem
modelo treinado.

## Ler um notebook sem estourar a janela

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -c "
import json
nb = json.load(open('notebooks/model_training.ipynb', encoding='utf-8'))
for i, c in enumerate(nb['cells']):
    s = ''.join(c['source'])
    if 'TERMO_PROCURADO' in s:
        print('===== CELL', i, c['cell_type'], '====='); print(s)
"
```

O `PYTHONIOENCODING=utf-8` não é opcional: sem ele o console do Windows quebra no primeiro acento.

## Modelos — o essencial

Os 18 artefatos de `models/` são de **três famílias do statsmodels**, um vencedor por série:
8 `SARIMAX` (`.pkl`), 7 `Theta` e 3 `ETS` (`.json`). Nenhum Prophet nem LSTM foi escolhido.
Servir é: refiltrar o estado com o dado real até a origem `D` (SARIMAX `res.apply(refit=False)`,
ETS `smooth(params)`; o Theta reajusta a cada chamada) e ler o **último** passo da projeção.

O que não está no artefato e muda o número sem erro nenhum vem do sidecar `.config.json`:
`transformacao` (`log1p` antes, `expm1` depois), a lista de exógenas **por série** e a
padronização delas (`exog_centro`/`exog_escala`). Mais a trava `2·max(série[D-27..D]) + 10`. Tudo
isso está implementado em `api/previsao.py`, e `tests/test_reproducao.py` reproduz as 534 origens
de `g_previsoes.csv` — rodar depois de qualquer mudança no serving.

`D+1` prevê a série `abertos` em 1 passo; `D+7` prevê a série `soma7` em 7 passos — e
`soma7(D+7)` **é**, por identidade, o acumulado de `D+1` a `D+7`. Detalhes, janelas, cortes e
exógenas: `docs/CONTRATO_MODELOS.md`.

## Documentos de referência

| Arquivo | Para quê |
|---|---|
| `README.md` | Porta de entrada: arquitetura, passo a passo de ponta a ponta, ponteiros. |
| `docs/CONTRATO_MODELOS.md` | Como servir os modelos. Ler antes de mexer em `api/`. |
| `docs/README_API.md` | Como subir a API e o container. |
| `3_gold_data/data_dictionary.md` | Desenho do treino, resultados e ressalvas, sem maquiagem. |

## Dois requirements, não intercambiáveis

- `requirements_notebooks.txt` — ambiente dos 3 notebooks (Spark, Prophet, torch, XGBoost, LLM).
- `requirements_api_container.txt` — mínimo de serving, o que entra na imagem.

As versões de `numpy`, `pandas`, `scipy` e `statsmodels` são idênticas nos dois de propósito
(compatibilidade do pickle). Subiu uma? Subir nos dois e retreinar.

`notebooks/data_validation.ipynb` roda em **PySpark** e exige Java 17+ no `PATH` — o `.venv` local
nunca teve pyspark instalado; a validação foi executada em Colab/WSL.

## Padrão de trabalho

O projeto trabalha por **spec**: escreve-se uma spec com contexto, restrições e critério de aceite,
e a implementação segue a spec. As specs históricas não estão versionadas — ao começar uma tarefa
grande, começar pelo `README.md` e pelo documento especializado da área.
