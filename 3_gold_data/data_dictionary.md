# Dicionário de dados — Gold

Saída de `notebooks/model_training.ipynb` (§11). São 3 tabelas escritas por `salvar()`, que valida
o contrato antes de gravar: a chave declarada no `CATALOGO` precisa existir, ser única e não ter
nulo — mesma função e mesmo contrato das camadas bronze e silver.

**Formato de todos os arquivos:** CSV, separador `;`, encoding `utf-8-sig`, sem índice.
Colunas de data são strings ISO `YYYY-MM-DD` (sem hora, sem fuso).

---

## Índice das tabelas

| Arquivo | Grão / chave | Linhas × colunas | Para quê |
|---|---|---|---|
| [`g_previsoes`](#g_previsoescsv) | data × prioridade × tipo_tratamento × horizonte × modelo | 1.200 × 9 | Toda previsão de teste, de **todos** os modelos, contra o valor real |
| [`g_avaliacao_modelos`](#g_avaliacao_modeloscsv) | tipo_tratamento × prioridade × horizonte × modelo | 120 × 14 | Quanto cada modelo errou (geral e por prioridade), contra o piso ingênuo, e qual foi escolhido |
| [`g_comparacao_grao`](#g_comparacao_graocsv) | horizonte × prioridade | 8 × 12 | Separar por tipo compensa? Soma de 2 modelos × modelo único sobre o total |

---

## O desenho por trás das três tabelas

### 9 séries em 3 grupos

O grão é `prioridade × tipo_tratamento`, e a coluna `tipo_tratamento` tem **três** valores nesta
camada — dois vindos do dado e um construído:

| Grupo | O que é | Janela | Dias | Teste |
|---|---|---|---|---|
| `com_intervencao` | Incidentes que exigiram trabalho humano | 2025-01-01 → 2025-12-31 | 365 | 2025-12-11 → 2025-12-31 (21 d, 3 semanas) |
| `sem_intervencao` | Incidentes que fecharam sozinhos via monitoramento | 2025-09-01 → 2025-12-31 | 122 | 2025-12-18 → 2025-12-31 (14 d, 2 semanas) |
| `total` | **Soma dos dois**, sem o grão de tipo | 2025-09-01 → 2025-12-31 | 122 | 2025-12-18 → 2025-12-31 (14 d, 2 semanas) |

`total` não é uma terceira categoria do dado — é `com_intervencao + sem_intervencao` agregado por
`data × prioridade`. Ele existe para responder uma pergunta de desenho: **separar por tipo valeu a
pena?** Fica restrito aos mesmos 122 dias de propósito; com os 365 dias de `com_intervencao` um
eventual ganho viria da janela maior, não do grão, e a comparação não responderia nada.

**Split único e cronológico**, sem embaralhamento e sem validação cruzada em várias dobras: o
teste é sempre a fatia mais recente. Cada modelo é ajustado uma vez por série.

### Os modelos

| Modelo | O que é | Entrada | Complexidade |
|---|---|---|---|
| `ARIMA` | Autorregressivo + média móvel sobre a série diferenciada | Só o histórico de `abertos` | 1 |
| `SARIMA` | ARIMA + bloco sazonal de período 7 + feriados como exógena | `abertos` + `feriado`, `vespera_feriado`, `pos_feriado` | 2 |
| `Prophet` | Modelo aditivo de curva: tendência + sazonalidade de Fourier + feriados | `ds`/`y`, sazonalidade semanal, tabela de feriados do projeto, `vespera_feriado` e `pos_feriado` como regressores | 3 |
| `LSTM` | Rede recorrente sobre janela de 14 dias | `log1p(abertos)` padronizado + 11 features de calendário por dia da janela + calendário do dia previsto | 4 |
| `Ingênuo` | A previsão de amanhã é o valor de hoje | `abertos` do dia de origem | — (piso, não candidato) |

Ordens de ARIMA/SARIMA escolhidas por **AIC** dentro do treino; `d` vem do teste ADF (resultou 0
nas 9 séries). O SARIMA venceu o ARIMA em AIC nas 9 séries.

**Nenhuma feature exógena entra** além do calendário. A restrição vem da recursão do D+7: para
prever D+2 o modelo precisaria do valor da exógena em D+1, que ainda não aconteceu. O custo dessa
restrição foi **medido, não assumido** — ver a nota sobre o estudo de features abaixo.

### Horizontes

`D+1` e `D+7` saem do **mesmo caminho de 7 passos** gerado a partir de cada dia de origem, o que
impede que os dois divirjam por acidente de implementação:

- **D+1** = primeiro passo do caminho. O modelo vê dado **real** até o dia de origem — legítimo,
  porque em produção o valor de hoje já é conhecido ao prever amanhã.
- **D+7** = **soma dos sete passos**, com a cadeia realimentando a própria previsão (o valor
  previsto de D+1 ocupa o lugar do real ao prever D+2, e assim por diante). Responde "quanto
  volume vem nesta semana", não "qual o valor do sétimo dia". Conferido contra
  `y_abertos_acum_1a7` da silver, com divergência 0.

O ARIMA/SARIMA andam pelo teste com os **parâmetros congelados**, refiltrando o estado com o dado
real até cada origem. O Prophet é **reajustado em cada origem** — ele não é autorregressivo e não
tem estado a atualizar, e sem o reajuste a comparação seria uma extrapolação de 3 semanas contra
modelos que enxergam o dia anterior. O LSTM é treinado uma vez e desliza a janela de entrada.

### O resultado, sem maquiagem

| Grupo | Horizonte | Vencedor | MAE | MASE | MAE do ingênuo | Supera o ingênuo? |
|---|---|---|---|---|---|---|
| `com_intervencao` | D+1 | SARIMA | 16,27 | 0,99 | **13,49** | ❌ −20,6 % |
| `com_intervencao` | D+7 | LSTM | **86,52** | 0,70 | 100,33 | ✅ +13,8 % |
| `sem_intervencao` | D+1 | SARIMA | 102,74 | 1,88 | **65,02** | ❌ −58,0 % |
| `sem_intervencao` | D+7 | SARIMA | 786,19 | 2,31 | **635,04** | ❌ −23,8 % |
| `total` | D+1 | ARIMA | 114,09 | 1,73 | **68,52** | ❌ −66,5 % |
| `total` | D+7 | ARIMA | 855,78 | 1,99 | **662,58** | ❌ −29,2 % |

**Apenas 1 de 6 vencedores supera o baseline ingênuo** — `com_intervencao` em D+7, com o LSTM.
Nos outros 5 casos o modelo escolhido erra mais do que simplesmente repetir o último valor
observado.

Isso não é falha de pipeline, é resultado. A decomposição STL mostra que o **resíduo responde por
58 % da média do nível** nas 9 séries; numa série assim, o ingênuo é forte porque se reancora todo
dia no nível corrente, enquanto um modelo ajustado numa janela fixa carrega o nível médio do
treino. **Recomendação de negócio: não colocar em produção um modelo que perde para o ingênuo** —
usar o próprio ingênuo como referência operacional enquanto não houver feature nova.

A tabela `g_avaliacao_modelos` guarda os 4 candidatos lado a lado com o ingênuo, para que essa
conclusão seja auditável, não uma alegação.

### O estudo de features (§4–§5 do notebook, não vira tabela gold)

93 features de 5 tabelas silver passaram por um XGBoost com importância medida por permutação no
teste. Dois achados que contextualizam as escolhas acima:

1. O ranking é liderado por **fluxo de fechamento / backlog** (31 % da importância), acima do
   passado da própria série (20 %). Um **teste de ablação** quantificou o que isso vale: remover
   as 64 exógenas e ficar só com as 29 que sobrevivem à recursão do D+7 custa **+13,1 % de MAE**.
2. Mas nem com todas as 93 features o modelo chega ao piso — o XGBoost completo **perde para o
   ingênuo por 24 %**. A parcela estocástica continua sem explicação dentro do que a base oferece
   hoje, e isso é o que limita o teto de todos os modelos desta camada.

---

# g_previsoes.csv

**Grão:** `data × prioridade × tipo_tratamento × horizonte × modelo` · **Chave:** as 5 colunas ·
**1.200 linhas × 9 colunas**.

Guarda a previsão de **todos os modelos**, não só do vencedor — é o que torna §8 e §9 do notebook
auditáveis a partir do arquivo, sem reexecutar nada.

### Chave

| Coluna | Tipo | Nulo | Domínio |
|---|---|---|---|
| `data` | date | 0 % | D+1: dia **previsto** (data-alvo). D+7: dia de **origem** (a semana prevista é `data+1` a `data+7`) |
| `prioridade` | int | 0 % | 2, 3, 4 |
| `tipo_tratamento` | str | 0 % | `com_intervencao`, `sem_intervencao`, `total` |
| `horizonte` | str | 0 % | `D+1`, `D+7` |
| `modelo` | str | 0 % | `ARIMA`, `SARIMA`, `Prophet`, `LSTM`, `Ingênuo` |

### Conteúdo

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `em_teste` | bool | 0 % | Sempre `True` — só previsões out-of-sample entram, nenhuma linha in-sample |
| `escolhido` | bool | 0 % | `True` se este modelo é o vencedor do seu grupo × horizonte (§9) |
| `valor_previsto` | float | 0 % | D+1: previsão de `abertos` para `data`. D+7: soma das 7 previsões recursivas. Nunca negativo, arredondado em 2 casas |
| `valor_real` | float | 0 % | D+1: `abertos` real em `data`. D+7: soma real de `abertos` em `data+1`…`data+7` (`y_abertos_acum_1a7`) |

### Cobertura

| Grupo | Origens D+1 | Linhas D+1 (3 prioridades × 5 modelos) | Origens D+7 | Linhas D+7 |
|---|---|---|---|---|
| `com_intervencao` | 21 | 315 | 15 | 225 |
| `sem_intervencao` | 14 | 210 | 8 | 120 |
| `total` | 14 | 210 | 8 | 120 |

O D+7 tem menos origens porque cada uma precisa de 7 dias reais **depois** dela para ter valor de
comparação — as últimas 6 origens do teste não têm.

---

# g_avaliacao_modelos.csv

**Grão:** `tipo_tratamento × prioridade × horizonte × modelo` · **Chave:** as 4 colunas ·
**120 linhas × 14 colunas** (3 grupos × 4 níveis de prioridade × 2 horizontes × 5 modelos).

`prioridade = "todas"` é a leitura **geral** (as 3 prioridades juntas), que é a que decide o
vencedor; as linhas `2`, `3`, `4` são o mesmo modelo fatiado por prioridade.

### Chave

| Coluna | Tipo | Nulo | Domínio |
|---|---|---|---|
| `tipo_tratamento` | str | 0 % | `com_intervencao`, `sem_intervencao`, `total` |
| `prioridade` | str | 0 % | `"todas"` (geral) ou `"2"`, `"3"`, `"4"` |
| `horizonte` | str | 0 % | `D+1`, `D+7` |
| `modelo` | str | 0 % | `ARIMA`, `SARIMA`, `Prophet`, `LSTM`, `Ingênuo` |

### Métricas

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `n` | int | 0 % | Pontos de teste avaliados |
| `mae` | float | 0 % | Erro absoluto médio, em incidentes/dia (D+1) ou incidentes/semana (D+7). **É a métrica de decisão** |
| `rmse` | float | 0 % | Raiz do erro quadrático médio |
| `mase` | float | 0 % | MAE ÷ erro da **mesma regra ingênua aplicada no treino**. Escala-livre: **< 1 = erra menos que o ingênuo cometia no treino**. É a métrica comparável **entre** séries |
| `mape` | float | 0 % | Erro percentual absoluto, com `max(y, 1)` no denominador. ⚠️ **Quebra nas séries de contagem baixa** (`com_intervencao` P4 tem dias com 0 e 1): valores de centenas de % são artefato do denominador, não erro real. Preferir `mase` |
| `mae_ingenuo` | float | 0 % | MAE do baseline ingênuo na mesma leitura, horizonte e datas — o piso |
| `ganho_vs_ingenuo` | float | 0 % | `(1 − mae/mae_ingenuo) × 100`. Negativo = perde para o ingênuo |
| `supera_ingenuo` | bool | 0 % | `mae < mae_ingenuo`. Sempre `False` nas linhas do próprio ingênuo |

`mase` e `ganho_vs_ingenuo` medem coisas próximas mas não idênticas: o `mase` compara com o
ingênuo **no treino** (referência estável), o `ganho_vs_ingenuo` com o ingênuo **no teste**
(mesmas datas). Divergência entre os dois é informação — significa que o período de teste foi mais
fácil ou mais difícil que o treino para uma previsão ingênua.

### Escolha

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `complexidade` | int | 0 % | 1 = ARIMA, 2 = SARIMA, 3 = Prophet, 4 = LSTM, 0 = ingênuo. É o critério de desempate |
| `escolhido` | bool | 0 % | Vencedor do grupo × horizonte. Uma linha `True` por combinação, sempre em `prioridade = "todas"` |

**Regra de escolha**, nesta ordem: (1) candidatos são os 4 modelos — o ingênuo **não concorre**;
(2) menor MAE na leitura geral; (3) empate técnico (diferença de MAE < 5 %) resolvido pelo **menos
complexo**; (4) se o vencedor perder para o ingênuo, isso é **registrado com destaque** e a
escolha se mantém, mas a leitura de negócio muda.

O passo (3) foi acionado em 2 dos 6 casos: `com_intervencao` D+1 (SARIMA no lugar do LSTM) e
`total` D+1 (ARIMA no lugar do SARIMA).

---

# g_comparacao_grao.csv

**Grão:** `horizonte × prioridade` · **Chave:** as 2 colunas · **8 linhas × 12 colunas**.

Responde à pergunta de desenho: para prever a **volumetria total** de uma prioridade, é melhor
somar dois modelos por tipo, ou treinar um modelo só sobre o total?

Os dois lados são medidos **nas mesmas datas** (2025-12-18 a 2025-12-31, a interseção das janelas
de teste) e contra o **mesmo valor real** — o notebook asserta que `real_com + real_sem` é idêntico
ao real do grupo `total`. Cada lado usa o modelo vencedor do seu próprio grupo.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `horizonte` | str | 0 % | `D+1`, `D+7` |
| `prioridade` | str | 0 % | `"todas"` (geral) ou `"2"`, `"3"`, `"4"` |
| `n` | int | 0 % | Pontos comparáveis (42 e 24 na leitura geral; 14 e 8 por prioridade) |
| `mae_soma_2_modelos` | float | 0 % | MAE de `previsto_com + previsto_sem` contra o real total |
| `mape_soma_2_modelos` | float | 0 % | MAPE da mesma soma |
| `mae_modelo_unico` | float | 0 % | MAE do modelo treinado sobre o total, sem o grão de tipo |
| `mape_modelo_unico` | float | 0 % | MAPE do modelo único |
| `vantagem_da_separacao` | float | 0 % | `(1 − mae_soma/mae_unico) × 100`. **Positivo = separar por tipo é melhor** |
| `modelo_com_intervencao` | str | 0 % | Vencedor usado no lado `com_intervencao` |
| `modelo_sem_intervencao` | str | 0 % | Vencedor usado no lado `sem_intervencao` |
| `modelo_total` | str | 0 % | Vencedor usado no lado do modelo único |
| `separacao_vence` | bool | 0 % | `vantagem_da_separacao > 0` |

### O resultado

| Horizonte | Soma de 2 modelos | Modelo único | Vantagem da separação |
|---|---|---|---|
| D+1 (geral) | **101,17** | 114,09 | **+11,3 %** |
| D+7 (geral) | **729,57** | 855,78 | **+14,7 %** |

**Nos dois horizontes a separação por tipo compensa.** As duas séries têm dinâmicas diferentes o
bastante para que modelá-las juntas custe acerto — a decisão de negócio de separar
`com_intervencao` de `sem_intervencao` se sustenta também pelo lado da previsão, não só pelo lado
da interpretação.

Uma exceção por prioridade: em **D+1 P4** o modelo único vence (−15,0 %), o único caso em que
juntar sai melhor. Em D+7 a separação vence nas 3 prioridades, com margem grande em P2 (+56,6 %).

⚠️ **Ressalva de tamanho de amostra.** São 42 pontos em D+1 e 24 em D+7 — o que a interseção das
janelas de teste permite. É indicativo, não conclusivo. Refazer com validação em várias origens
(*rolling origin*) daria uma resposta mais firme, e está registrado como próximo passo no
notebook.
