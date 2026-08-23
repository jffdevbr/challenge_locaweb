# Dicionário de dados — Gold

Saída da Seção 8 de `notebooks/model_training.ipynb`. São 2 tabelas escritas por `salvar()`, que
valida o contrato antes de gravar: a chave declarada no `CATALOGO` precisa existir, ser única e
não ter nulo — mesma função e mesmo contrato das camadas bronze e silver.

**Formato de todos os arquivos:** CSV, separador `;`, encoding `utf-8-sig`, sem índice.
Colunas de data são strings ISO `YYYY-MM-DD` (sem hora, sem fuso).

---

## Índice das tabelas

| Arquivo | Grão / chave | Linhas × colunas | Para quê |
|---|---|---|---|
| [`g_previsoes`](#g_previsoescsv) | data × prioridade × tipo_tratamento × horizonte × em_treino | 3.879 × 7 | O número previsto, dia a dia, pelo modelo vencedor de cada série |
| [`g_avaliacao_modelos`](#g_avaliacao_modeloscsv) | prioridade × tipo_tratamento × horizonte × modelo × escopo | 45 × 17 | Quanto cada candidato errou, contra o piso, e qual venceu |

---

## Convenções que atravessam as duas tabelas

**As 6 séries.** Todo o conteúdo desta camada é organizado pelas mesmas 6 séries alvo da silver:
prioridade (2, 3, 4) × `tipo_tratamento` (`com_intervencao`, `sem_intervencao`). Formato longo,
como nas camadas anteriores — série é linha, nunca coluna.

**Janela de treino/teste.** Regra literal do enunciado, aplicada igual às três prioridades dentro
de cada tipo:

| `tipo_tratamento` | Janela | Dias |
|---|---|---|
| `com_intervencao` | 2025-01-01 a 2025-12-31 | 365 |
| `sem_intervencao` | 2025-09-01 a 2025-12-31 | 122 |

As quebras estruturais finas identificadas na exploração (P3 `com_intervencao` em 25/10; o
breakpoint de `sem_intervencao` em 31/08–01/09) são **conscientemente ignoradas** — decisão de
negócio para manter a regra simples, não omissão. O custo dessa decisão está quantificado nas
linhas `sem_intervencao` de `g_avaliacao_modelos`.

**Validação.** Rolling-origin (`TimeSeriesSplit`, `gap=1`, sem shuffle), com o tamanho do teste
fixo por dobra:

| `tipo_tratamento` | Dobras | Teste por dobra | Treino (1ª → última dobra) | Dias avaliados por série |
|---|---|---|---|---|
| `com_intervencao` | 6 | 40 dias | 124 → 324 dias | 240 |
| `sem_intervencao` | 4 | 15 dias | 61 → 106 dias | 60 |

**Horizontes.** `D+1` é o modelo. `D+7` é o **mesmo modelo aplicado recursivamente** sete vezes,
realimentando a própria previsão — não existe modelo direto de D+7 nem cadeia por passo. O erro
dos dois é reportado em linhas separadas, nunca somado.

**Features.** Conjunto fechado de 19 colunas, restrito pelo desenho recursivo: 11 de calendário e
8 de lag/janela móvel do próprio alvo (`lag_1`, `lag_2`, `lag_3`, `lag_7`, `lag_14`, `media_7d`,
`media_14d`, `media_30d`). No modelo `pooled` somam-se 3 indicadoras de prioridade. **Nenhuma
feature exógena** (IC, template, equipe, backlog, outra prioridade) entra: todas são medidas do
mesmo dia que o alvo e não são conhecidas em D+3 sem serem elas próprias previstas.

**Baselines de referência.** Quatro, medidos exatamente nas mesmas datas que os modelos: ingênuo
(`abertos[O]`), sazonal lag-7 (`abertos[D−7]`), MM7 e MM30 (médias dos 7 e 30 dias até a origem
`O = D − h`). Em h = 7 o ingênuo e o sazonal lag-7 coincidem por definição.

---

# g_previsoes.csv

**Grão:** `data × prioridade × tipo_tratamento × horizonte × em_treino` ·
**Chave:** as 5 colunas acima · **3.879 linhas × 7 colunas**.

A previsão do **modelo vencedor** de cada série — só dele. As previsões dos candidatos perdedores
ficam fora: o que se avalia deles está em `g_avaliacao_modelos`.

> **Por que `em_treino` está na chave.** O grão pedido no handoff é
> `data × prioridade × tipo_tratamento × horizonte`, mas a mesma data aparece duas vezes quando se
> guarda tanto a previsão out-of-fold quanto a in-sample do modelo final — que é o que a própria
> coluna `em_treino` existe para distinguir. Sem ela na chave as duas linhas colidiriam e
> `salvar()` recusaria a gravação.

### Chave

| Coluna | Tipo | Nulo | Domínio |
|---|---|---|---|
| `data` | date | 0 % | Dia **previsto** (data-alvo, não a origem da previsão). Dentro da janela da série |
| `prioridade` | int | 0 % | 2, 3, 4 |
| `tipo_tratamento` | str | 0 % | `com_intervencao`, `sem_intervencao` |
| `horizonte` | str | 0 % | `D+1`, `D+7` |
| `em_treino` | bool | 0 % | Ver abaixo |

### Conteúdo

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `modelo` | str | 0 % | Nome do modelo que gerou a previsão. `GLM Poisson`, `Gradient Boosting`, `MLP` ou `Baseline <nome>` |
| `valor_previsto` | float | 0 % | Previsão de `abertos` para `data`, arredondada em 2 casas. Nunca negativa — o corte em zero faz parte da definição do preditor |

### `em_treino` — a coluna que diz o quanto confiar na linha

| Valor | O que é | Para que serve |
|---|---|---|
| `False` | Previsão **out-of-fold**: o dia não participou do ajuste do modelo que o previu | É a única honesta para medir erro. Toda métrica de `g_avaliacao_modelos` vem daqui |
| `True` | Previsão **in-sample** do modelo final, reajustado em toda a janela | Cobre a janela inteira, serve para inspeção visual e para reconstruir a série ajustada. **Não usar para medir erro** |

### Cobertura por série

| Série | Vencedor | D+1 OOF | D+1 in-sample | D+7 OOF | D+7 in-sample |
|---|---|---|---|---|---|
| P2 `com_intervencao` | GLM Poisson (pooled) | 240 | 365 | 210 | 358 |
| P3 `com_intervencao` | Gradient Boosting (pooled) | 240 | 365 | 210 | 358 |
| P4 `com_intervencao` | GLM Poisson (individual) | 240 | 365 | 210 | 358 |
| P2 `sem_intervencao` | Baseline MM30 | 60 | — | 60 | — |
| P3 `sem_intervencao` | Baseline ingênuo | 60 | — | 60 | — |
| P4 `sem_intervencao` | Baseline ingênuo | 60 | — | 60 | — |

Três leituras de cobertura que evitam conclusão errada:

- **As linhas OOF não cobrem a janela inteira.** Os primeiros dias de cada janela nunca são teste
  de dobra nenhuma — é assim que rolling-origin funciona. Quem cobre a janela inteira são as
  linhas `em_treino=True`.
- **O D+7 tem menos linhas OOF que o D+1** (210 contra 240). Uma previsão de sete passos feita na
  origem `O` só é legítima se o modelo tiver sido treinado apenas com dados até `O`; as datas-alvo
  cuja origem cairia dentro do treino foram descartadas em vez de aceitas com vazamento.
- **Séries com vencedor-baseline não têm linha `em_treino=True`.** Baseline não tem ajuste: para
  ele, in-sample e out-of-fold seriam a mesma conta.

---

# g_avaliacao_modelos.csv

**Grão:** `prioridade × tipo_tratamento × horizonte × modelo × escopo` ·
**Chave:** as 5 colunas acima · **45 linhas × 17 colunas**.

Todos os candidatos avaliados, não só os vencedores. São 36 linhas de D+1 (6 séries × 3 modelos ×
2 escopos), 3 linhas de D+1 dos baselines que venceram a própria série, e 6 linhas de D+7 — uma
por série, porque o D+7 é gerado exclusivamente pelo vencedor de D+1.

### Chave

| Coluna | Tipo | Nulo | Domínio |
|---|---|---|---|
| `prioridade` | int | 0 % | 2, 3, 4 |
| `tipo_tratamento` | str | 0 % | `com_intervencao`, `sem_intervencao` |
| `horizonte` | str | 0 % | `D+1`, `D+7` |
| `modelo` | str | 0 % | `GLM Poisson`, `Gradient Boosting`, `MLP`, `Baseline MM30`, `Baseline ingênuo` |
| `escopo` | str | 0 % | `pooled`, `individual`, `baseline` |

### `escopo` — a resposta ao Objetivo 1

| Valor | O que é |
|---|---|
| `pooled` | Um modelo por `tipo_tratamento`, treinado nas 3 prioridades juntas, com a prioridade entrando como indicadora |
| `individual` | Um modelo por série |
| `baseline` | Não é modelo aprendido: é o melhor baseline da série, promovido a entregável porque nenhum candidato superou o piso |

### Métricas (todas na validação out-of-fold)

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `mae` | float | 0 % | Erro absoluto médio, em incidentes/dia. **É a métrica de decisão** |
| `rmse` | float | 0 % | Raiz do erro quadrático médio. Penaliza o pico isolado, que é o que separa P2 das demais |
| `mape` | float | 0 % | Erro percentual absoluto médio, com `max(y, 1)` no denominador para não estourar em dia de volume baixo |
| `melhor_baseline` | float | 0 % | MAE do melhor baseline da mesma série e horizonte — o piso |
| `supera_baseline` | bool | 0 % | `mae < melhor_baseline`. **Sempre `False` nas linhas de `escopo = baseline`**: um baseline não supera a si mesmo |

### Contexto do ajuste

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `janela_treino_inicio` | date | 0 % | `2025-01-01` (com) / `2025-09-01` (sem) |
| `janela_treino_fim` | date | 0 % | `2025-12-31` nos dois |
| `n_treino` | int | 0 % | Dias de treino por série, média entre as dobras. `0` nas linhas de baseline, que não treinam |
| `n_teste` | int | 0 % | Linhas efetivamente avaliadas. 240 (D+1 com) · 210 (D+7 com) · 60 (sem) |

### Escolha e explicabilidade

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `escolhido` | bool | 0 % | Vencedor da série/horizonte. Exatamente uma linha `True` por combinação série × horizonte |
| `top_features` | str | 0 % (`""` fora do vencedor) | As 5 features de maior importância por permutação, separadas por ` · ` |
| `fonte_principal` | str | 0 % (`""` fora do vencedor) | Categoria que soma mais importância: `calendário`, `lag-rolling do alvo`, `dimensão da série` ou `exógeno-congelado` (esta última sempre vazia — nenhuma exógena foi admitida) |

**Regra de escolha do vencedor**, aplicada nesta ordem: (1) descartar quem não supera o piso;
(2) menor MAE; (3) em empate técnico — diferença de MAE menor que 2 % — o mais simples, com GLM
antes de Gradient Boosting antes de MLP, e `pooled` antes de `individual`. Quando nenhum candidato
sobrevive ao passo (1), o vencedor é o próprio baseline.

### O resultado, resumido

| Série | Vencedor D+1 | MAE | Piso | Ganho | MAE D+7 | Supera piso em D+7? |
|---|---|---|---|---|---|---|
| P2 `com_intervencao` | GLM Poisson · pooled | 15,95 | 17,55 | +9,1 % | 14,57 | sim |
| P3 `com_intervencao` | Gradient Boosting · pooled | 15,35 | 17,29 | +11,2 % | 19,64 | **não** |
| P4 `com_intervencao` | GLM Poisson · individual | 7,56 | 8,43 | +10,3 % | 7,62 | sim |
| P2 `sem_intervencao` | Baseline MM30 | 36,54 | 36,54 | — | 36,07 | — |
| P3 `sem_intervencao` | Baseline ingênuo | 51,25 | 51,25 | — | 81,55 | — |
| P4 `sem_intervencao` | Baseline ingênuo | 51,82 | 51,82 | — | 79,25 | — |

Dois avisos para quem consumir esta tabela sem abrir o notebook:

1. **Metade das séries não tem modelo aprendido.** Nas três `sem_intervencao`, nenhum dos três
   candidatos superou o piso — 122 dias de histórico contra uma mudança de patamar em dezembro. O
   que a camada entrega para elas é o baseline, explicitamente marcado em `escopo`.
2. **P3 `com_intervencao` vence em D+1 e perde em D+7.** O modelo depende de lag, e na recursão o
   lag passa a ser a própria previsão: +28 % de MAE em sete passos. A linha de D+7 dessa série tem
   `supera_baseline = False` e isso não é inconsistência com a linha de D+1 — é o custo do desenho
   recursivo, medido.
