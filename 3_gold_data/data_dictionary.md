# Dicionário de dados — Gold

Saída de `notebooks/model_training.ipynb` (§11). São 4 tabelas escritas por `salvar()`, que valida
o contrato antes de gravar: a chave declarada no `CATALOGO` precisa existir, ser única e não ter
nulo — mesma função e mesmo contrato das camadas bronze e silver.

**Formato de todos os arquivos:** CSV, separador `;`, encoding `utf-8-sig`, sem índice.
Colunas de data são strings ISO `YYYY-MM-DD` (sem hora, sem fuso).

> ⚠️ **Esta versão mudou o desenho do treino.** Os dois horizontes passaram a ser treinados
> separadamente e previstos de forma **direta**; o piso ingênuo do D+7 mudou de regra; e os
> tamanhos de teste foram redimensionados. **Números desta versão não são comparáveis com os da
> anterior**, em particular `mae_ingenuo` e tudo que deriva dele no horizonte D+7. As seções
> *Horizontes* e *O piso do D+7 subiu* explicam o quê e o porquê.

---

## Índice das tabelas

| Arquivo | Grão / chave | Linhas × colunas | Para quê |
|---|---|---|---|
| [`g_previsoes`](#g_previsoescsv) | data × prioridade × tipo_tratamento × horizonte × modelo | 2.670 × 9 | Toda previsão de teste, de **todos** os modelos, contra o valor real |
| [`g_avaliacao_modelos`](#g_avaliacao_modeloscsv) | tipo_tratamento × prioridade × horizonte × modelo | 120 × 17 | Quanto cada modelo errou (geral e por prioridade), contra o piso ingênuo, e qual foi escolhido |
| [`g_comparacao_grao`](#g_comparacao_graocsv) | horizonte × prioridade | 8 × 12 | Separar por tipo compensa? Soma de 2 modelos × modelo único sobre o total |
| [`g_ablacao_exogenas`](#g_ablacao_exogenascsv) | tipo_tratamento × horizonte × medidor | 8 × 12 | Quanto valem as features exógenas, nos dois horizontes, com o efeito mínimo detectável ao lado |

---

## O desenho por trás das quatro tabelas

### 9 séries em 3 grupos

O grão é `prioridade × tipo_tratamento`, e a coluna `tipo_tratamento` tem **três** valores nesta
camada — dois vindos do dado e um construído:

| Grupo | O que é | Janela | Dias | Teste |
|---|---|---|---|---|
| `com_intervencao` | Incidentes que exigiram trabalho humano | 2025-01-01 → 2025-12-31 | 365 | 2025-11-20 → 2025-12-31 (42 d, 6 semanas) |
| `sem_intervencao` | Incidentes que fecharam sozinhos via monitoramento | 2025-09-01 → 2025-12-31 | 122 | 2025-12-04 → 2025-12-31 (28 d, 4 semanas) |
| `total` | **Soma dos dois**, sem o grão de tipo | 2025-09-01 → 2025-12-31 | 122 | 2025-12-04 → 2025-12-31 (28 d, 4 semanas) |

`total` não é uma terceira categoria do dado — é `com_intervencao + sem_intervencao` agregado por
`data × prioridade`. Ele existe para responder uma pergunta de desenho: **separar por tipo valeu a
pena?** Fica restrito aos mesmos 122 dias de propósito; com os 365 dias de `com_intervencao` um
eventual ganho viria da janela maior, não do grão, e a comparação não responderia nada.

As contagens de diversidade do grupo `total` (`ics_distintos`, `times_distintos`,
`descricoes_distintas`) são a **soma** das dos dois tipos, o que conta duas vezes um IC que
apareceu nos dois no mesmo dia. É um limite superior; a contagem exata exigiria voltar ao grão do
incidente. As razões `inc_por_*` do `total`, essas, são reconstruídas de numerador e denominador
somados antes de dividir — somar duas razões não significaria nada.

**Split único e cronológico**, sem embaralhamento e sem validação cruzada em várias dobras: o
teste é sempre a fatia mais recente. Cada modelo é ajustado uma vez por série e por horizonte.

### Os modelos

Cada série tem **dois** modelos de cada família — um por horizonte, ajustados em séries
diferentes. É a mudança de desenho desta versão.

| Modelo | D+1 — série diária `abertos` | D+7 — série agregada `soma7` | Complexidade |
|---|---|---|---|
| `ARIMA` | Autorregressivo + média móvel. Só o histórico de `abertos` | O mesmo sobre a soma móvel. A grade de `q` vai até **7**: a agregação induz média móvel de ordem 6, porque janelas vizinhas compartilham 6 dias | 1 |
| `SARIMA` | ARIMA + bloco sazonal de período 7 + `feriado`, `vespera_feriado`, `pos_feriado` | **Sem bloco sazonal** — 7 dias consecutivos têm sempre um de cada dia da semana, então a sazonalidade semanal não sobrevive à agregação. Resta ARIMA + `feriados_7d`, `vesperas_7d` | 2 |
| `Prophet` | Tendência plana + sazonalidade semanal + tabela de feriados + regressores de véspera/pós | Tendência plana, **sem sazonalidade semanal** e **sem tabela de feriados** — num total semanal o feriado é uma contagem, não um ponto, e entra como regressor `feriados_7d` | 3 |
| `LSTM` | Janela de 14 dias → o valor de amanhã | Janela de 14 dias → a soma dos 7 dias seguintes, **numa aplicação só** | 4 |
| `Ingênuo` | O valor de hoje | A melhor das duas regras, escolhida **dentro do treino** — ver *O piso do D+7 subiu* | — (piso, não candidato) |

Ordens escolhidas por **AIC** dentro do treino; `d` vem do teste ADF. Uma leitura que confirma o
argumento da grade: **as 9 séries de D+7 escolheram `q = 7`** — a grade da versão anterior, que
parava em `q = 3`, não teria como representar a estrutura que a soma móvel induz. No agregado o
ADF também passou a pedir `d = 1` na maioria das séries, contra `d = 0` em todas as diárias.

**A entrada do LSTM inclui 10 features exógenas**, o que era impossível no desenho anterior:
`inc_por_ic`, `inc_por_descricao`, `inc_por_time`, `fechados`, `backlog`,
`saldo_aberto_fechado`, `abertos_sem_classificacao`, `ics_distintos`, `times_distintos`,
`descricoes_distintas`. O conjunto é **pré-registrado**: foi fixado a partir da leitura por
*família* de §5.5, e não do ranking por permutação de §5.3 — aquele é calculado no teste, e
usá-lo para selecionar features vazaria o teste para dentro do modelo.

### Horizontes

**Os dois horizontes são treinados separadamente, e os dois são previstos de forma direta.**
Esta é a mudança central em relação à versão anterior deste documento.

- **D+1** — modelo ajustado na série diária `abertos`, previsão a 1 passo. O modelo vê dado
  **real** até o dia de origem, o que é legítimo: em produção o valor de hoje já é conhecido ao
  prever amanhã.
- **D+7** — modelo ajustado na **série agregada** `soma7`, a soma móvel de 7 dias fechando em D,
  previsão a 7 passos. Sustenta-se numa identidade exata:

  ```
  soma7(D)   = abertos[D-6] + ... + abertos[D]
  soma7(D+7) = abertos[D+1] + ... + abertos[D+7] = y_abertos_acum_1a7(D)
  ```

  Prever `soma7` sete passos à frente **é** o acumulado de D+1 a D+7. Conferido contra
  `y_abertos_acum_1a7` da silver, com divergência 0.

**Por que mudou.** A versão anterior gerava o D+7 por **recursão** — o modelo de D+1 aplicado
sete vezes, com a própria previsão realimentada. Isso impunha que **nenhuma feature exógena
pudesse entrar em nenhum dos dois horizontes**: para prever D+2 o modelo precisaria das features
de D+1, que ainda não aconteceu. A restrição, porém, nunca veio do horizonte — veio da recursão.
Um modelo direto não precisa de valor futuro de feature nenhuma.

O preço da recursão também estava medido: o LSTM em `sem_intervencao` saía de 138,7 de MAE em
D+1 para **1.081,6** em D+7, contra 635,0 do ingênuo. Não era o horizonte que era difícil; era o
erro do passo 1 entrando como dado no passo 2, sete vezes.

O ARIMA/SARIMA andam pelo teste com os **parâmetros congelados**, refiltrando o estado com o dado
real até cada origem. O Prophet é **reajustado em cada origem** — ele não é autorregressivo e não
tem estado a atualizar. O LSTM é treinado uma vez por série e por horizonte.

### O piso do D+7 subiu

Em D+1 o ingênuo é uma regra só: a previsão de amanhã é o valor de hoje. Em D+7 há duas regras
plausíveis, e elas **não empatam**:

- `7 × abertos[D]` — repetir o dia de hoje sete vezes. Era a regra da versão anterior, e ela
  amplifica o ruído de um único dia por sete;
- `soma7[D]` — a soma da última semana, a regra natural para um total semanal.

Nenhuma domina: a soma da última semana é melhor onde a série é estável e pior onde ela sobe
forte, porque a média móvel atrasa. A regra é escolhida **dentro do treino**, série a série, e a
escolhida fica gravada na coluna `regra_ingenua` — `soma da última semana` venceu em **7 das 9
séries**. Escolher a melhor no teste seria espiar o teste para calibrar o adversário.

Isso muda o placar antes de mudar qualquer modelo. Na versão anterior, contra `7 × abertos[D]`, o
vencedor de `com_intervencao` D+7 aparecia ganhando do ingênuo por 13,5 %; contra `soma7[D]`
medido nas mesmas origens (82,9 de MAE contra os 86,8 dele), ele perderia.

### Amostras sobrepostas, embargo e o tamanho do teste

O D+7 treina em **origens diárias com janelas sobrepostas** — uma linha por dia, cada uma olhando
os 7 dias seguintes. Origens semanais não sobrepostas seriam 52 linhas em `com_intervencao` e 17
em `sem_intervencao`, o que não treina nada. A sobreposição cobra três cuidados, todos
implementados e verificados em §12.1 do notebook:

1. **Embargo** (*purged split*): a origem imediatamente anterior ao corte teria alvo cobrindo dias
   do teste. Só são amostras de treino as origens cujo alvo inteiro cai antes do corte, o que
   descarta as 6 últimas no D+7. É o tipo de erro que não apareceria como falha — apareceria como
   um resultado bom demais.
2. **Informação efetiva menor que o número de linhas**: a autocorrelação do alvo acumulado é 0,90
   no lag 1 e cai a ~0 no lag 7, o que dá `n_efetivo / n ≈ 0,17`. As 316 amostras de
   `com_intervencao` valem por ~54 semanas independentes. É esse número, e não o 316, que limita
   o tamanho do modelo — daí as 10 exógenas no LSTM, e não as 67 do painel.
3. **Correção na avaliação**: o *nível* do alvo tem fator de inflação de variância ≈ 6, mas o
   *erro* e a *diferença pareada entre modelos* têm VIF ≈ 2 — o modelo absorve o nível
   autocorrelacionado e o resíduo fica perto de ruído. É esse VIF que entra no `mde` de
   `g_ablacao_exogenas`.

Como salvaguarda adicional, §8.6 do notebook refaz a leitura principal usando **só uma origem a
cada 7** (o maior subconjunto com alvos disjuntos) e confere que o vencedor não muda: **o melhor
modelo coincide nos 6 cortes**. Sobram 3 a 5 pontos por série, então isso não é conclusivo
sozinho — serve para detectar o caso em que a sobreposição estaria fabricando uma diferença.

**Os tamanhos de teste foram dimensionados, não escolhidos por hábito.** Medindo em `g_previsoes`
o desvio-padrão da diferença pareada de erro absoluto entre dois modelos próximos, o efeito
mínimo detectável a 80 % de poder ficou:

| grupo | horizonte | 21 d | 28 d | 42 d |
|---|---|---|---|---|
| `com_intervencao` | D+1 | 29,0 % | 25,1 % | **20,5 %** |
| `com_intervencao` | D+7 | 24,6 % | 20,3 % | **15,9 %** |
| `sem_intervencao` | D+1 | 23,3 % | **20,2 %** | 16,5 % |
| `sem_intervencao` | D+7 | 15,2 % | **12,6 %** | 10,9 % |

Em `com_intervencao` 28 dias dariam um MDE acima do efeito procurado — ali o teste é de 42 dias,
e esticar não custa (365 dias de janela). Nos outros dois grupos só existem 122 dias desde a
quebra de 2025-09-03 e cada dia de teste sai do treino, então ficam 28. O que nenhum corte
resolve: em `sem_intervencao` e `total` o D+1 não fica decisivo abaixo de ~15–20 %. Isso é
restrição de histórico, não falha de método — e não se resolveria com validação em várias origens,
que reusaria o mesmo dado finito.

### O resultado, sem maquiagem

| Grupo | Horizonte | Vencedor | MAE | MASE | MAE do ingênuo | Regra do ingênuo | Supera o ingênuo? |
|---|---|---|---|---|---|---|---|
| `com_intervencao` | D+1 | SARIMA | 16,21 | 0,95 | **15,87** | último valor | ❌ −2,2 % |
| `com_intervencao` | D+7 | ARIMA | **58,20** | 0,90 | 91,90 | soma da última semana | ✅ **+36,7 %** |
| `sem_intervencao` | D+1 | ARIMA | 85,83 | 1,55 | **54,13** | último valor | ❌ −58,6 % |
| `sem_intervencao` | D+7 | ARIMA | 563,14 | 1,90 | **458,86** | mista por prioridade | ❌ −22,7 % |
| `total` | D+1 | ARIMA | 82,21 | 1,23 | **59,21** | último valor | ❌ −38,8 % |
| `total` | D+7 | ARIMA | 555,80 | 1,58 | **462,97** | mista por prioridade | ❌ −20,1 % |

**1 de 6 vencedores supera o baseline ingênuo** — mas esse caso mudou de natureza. Em
`com_intervencao` D+7 os **quatro** candidatos passam a superar o piso, e por margem larga:

| Modelo | MAE | vs. ingênuo |
|---|---|---|
| SARIMA | **55,89** | +39,2 % |
| ARIMA | 58,20 | +36,7 % |
| LSTM | 82,16 | +10,6 % |
| Prophet | 88,67 | +3,5 % |
| Ingênuo | 91,90 | — |

(O ARIMA é o escolhido, não o SARIMA: a diferença de 4 % cai dentro da tolerância de empate
técnico de 5 %, e a regra manda ficar com o menos complexo.)

**De onde veio esse ganho — e não é de onde se esperava.** Quem vence ali é ARIMA/SARIMA **sobre
a série agregada**, não o LSTM que recebeu as exógenas. O que produziu o resultado foi **tirar a
recursão**, não acrescentar feature. O desenho anterior compunha erro por sete passos, e era isso
que dominava o horizonte longo. A mudança de features, medida isoladamente em `g_ablacao_exogenas`,
fica dentro do ruído em 5 dos 6 cortes.

Nos outros 5 cortes o ingênuo continua ganhando, e a leitura de §3 continua valendo: o resíduo do
STL responde por **58 % da média do nível** nas 9 séries. Numa série assim o ingênuo é forte
porque se reancora todo dia no nível corrente. **Recomendação de negócio: usar o modelo em
produção apenas onde ele supera o ingênuo** — hoje, `com_intervencao` em D+7 — e o próprio
ingênuo como referência operacional nos demais.

### O estudo de features (§4–§5 do notebook)

96 features passaram por um XGBoost com importância medida por permutação no teste, nas 9 séries
empilhadas. O ranking é liderado por **contexto do dia** (26 %) e **fluxo de fechamento /
backlog**, acima do passado da própria série (13 %).

O **teste de ablação** quantifica o que a parte exógena vale, agora nos **dois** horizontes:

| Horizonte | MAE com as 67 exógenas | MAE só com as 29 conhecidas em D | Custo de remover | MAE do ingênuo |
|---|---|---|---|---|
| D+1 | 44,03 | 49,68 | **+12,8 %** | 39,00 |
| D+7 | **261,92** | 303,52 | **+15,9 %** | 272,29 |

Dois achados:

1. **As exógenas ajudam mais o horizonte longo** (+15,9 % contra +12,8 %) — justamente onde o
   desenho anterior ia pior. É o que motivou abandonar a recursão.
2. **Em D+7, o modelo completo supera o ingênuo** (261,92 contra 272,29, +3,8 %), enquanto o
   restrito perde por 11,5 %. No horizonte longo, as exógenas são o que separa ganhar do piso de
   perder dele — no XGBoost diagnóstico.

Em D+1 nem o modelo completo chega ao piso (44,03 contra 39,00, −13 %). A parcela estocástica
continua sem explicação dentro do que a base oferece hoje, e isso é o que limita o teto no
horizonte curto.

> **Nota de método.** Estes números são média de 8 sementes do XGBoost, não de um ajuste único.
> O MAE de um ajuste isolado varia por causa de `subsample` e `colsample_bytree` mais do que a
> diferença entre a maioria dos conjuntos de features comparados. Uma leitura de semente única
> aqui mede a semente, não a feature.

### Concentração do evento: o que deu certo

Três colunas foram acrescentadas a `s_fato_diario_prioridade` — `inc_por_ic`,
`inc_por_descricao` e `inc_por_time`, ou seja `abertos` dividido por cada uma das três contagens
de diversidade que a tabela já tinha.

Elas separam o que a contagem bruta funde: **400 incidentes espalhados por 200 ICs é volume alto
de operação normal; 400 incidentes em 3 ICs é um incidente sistêmico.** As duas situações têm o
mesmo `abertos`, e `ics_distintos` isolado também não as distingue.

| Grupo de razões | Δ MAE pareada | t | ajuda em |
|---|---|---|---|
| **concentração do evento (3)** | **−2,50 (−4,8 %)** | **−5,38** | **26/30 sementes** |
| todas as 11 razões testadas | −2,30 (−4,4 %) | −4,28 | 25/30 |
| fluxo e fila (4) | −0,43 (−0,8 %) | −0,89 | 18/30 |
| composição do dia (3) | −0,23 (−0,4 %) | −0,54 | 18/30 |
| parque de ICs (1) | −0,12 (−0,2 %) | −0,34 | 14/30 |

Teste **pareado** (mesma semente nos dois modelos, 30 sementes), que remove a variância
compartilhada e é muito mais sensível que comparar médias independentes. As três de concentração
são melhores sozinhas do que as 11 juntas — as outras oito só acrescentam ruído.

**Por que estas funcionam onde time e descrição falharam.** Numerador e denominador já estavam
ambos no modelo. A razão não traz dado novo — traz uma **relação** que um modelo de árvore só
aproximaria com muitos cortes sucessivos, e que por isso ele tende a não encontrar sozinho.

**Nesta versão as três entram nos modelos de §7**, pelo LSTM, o que no desenho recursivo era
impossível. Quanto isso rendeu está em `g_ablacao_exogenas` e é sóbrio — ver abaixo.

### Time responsável e descrição resumida: testados, e fora do modelo

`Grupo designado` (17 times) e `Descrição Resumida` (13.317 templates → 11 classes) ganharam
tabelas silver no grão `data × prioridade × tipo_tratamento` e foram codificados de duas formas:
**share em janela** (`lag1`, `7d`, `30d`) e **frequency encoding expansivo**.

A **contagem** inteira por bucket nunca vira feature: as contagens somam exatamente `abertos`, ou
seja, são o alvo reescrito em outra base, e `abertos` já entra no modelo como lag 1. Elas existem
como matriz intermediária, e a propriedade de somarem `abertos` é usada como prova de que o pivot
não perdeu nem duplicou incidente.

**Resultado: nenhuma das 15 configurações testadas reduz o erro além do ruído entre sementes.**
Três leituras: a janela não salvou o encoding (o problema não era o encoding); quanto maior a
janela, pior (a composição de um mês é quase constante, então essas colunas trazem pouca variação
e muito parâmetro); e a dimensionalidade domina — blocos de 11, 21 ou 80 colunas custam variância
que nenhum ganho de sinal compensa.

**Decisão: nenhum 5º modelo candidato foi aberto, e as colunas ficam no painel de §4, fora do
modelo.** O caminho que o resultado aponta não é mais feature engineering sobre a mesma base — é
**mais histórico**.

---

# g_previsoes.csv

**Grão:** `data × prioridade × tipo_tratamento × horizonte × modelo` · **Chave:** as 5 colunas ·
**2.670 linhas × 9 colunas**.

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
| `valor_previsto` | float | 0 % | D+1: previsão de `abertos` para `data`. D+7: previsão **direta** do acumulado de `data+1` a `data+7` — não é mais a soma de 7 previsões. Nunca negativo, arredondado em 2 casas |
| `valor_real` | float | 0 % | D+1: `abertos` real em `data`. D+7: soma real de `abertos` em `data+1`…`data+7` (`y_abertos_acum_1a7`) |

### Cobertura

| Grupo | Origens D+1 | Linhas D+1 (3 prioridades × 5 modelos) | Origens D+7 | Linhas D+7 |
|---|---|---|---|---|
| `com_intervencao` | 42 | 630 | 36 | 540 |
| `sem_intervencao` | 28 | 420 | 22 | 330 |
| `total` | 28 | 420 | 22 | 330 |

O D+7 tem 6 origens a menos porque cada uma precisa de 7 dias reais **depois** dela para ter valor
de comparação — as últimas 6 do teste não têm. É a mesma janela de 7 dias que, do outro lado da
fronteira, tira 6 origens do fim do treino (o embargo).

---

# g_avaliacao_modelos.csv

**Grão:** `tipo_tratamento × prioridade × horizonte × modelo` · **Chave:** as 4 colunas ·
**120 linhas × 17 colunas** (3 grupos × 4 níveis de prioridade × 2 horizontes × 5 modelos).

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
| `mape` | float | 0 % | Erro percentual absoluto, com `max(y, 1)` no denominador. ⚠️ **Quebra nas séries de contagem baixa**: valores de centenas de % são artefato do denominador. Preferir `mase` |
| `mae_ingenuo` | float | 0 % | MAE do baseline ingênuo na mesma leitura, horizonte e datas — o piso |
| `regra_ingenua` | str | 0 % | **Nova.** Qual regra define o piso: `último valor` (D+1); em D+7, `soma da última semana` ou `7 x abertos[D]`, escolhida no treino. Nas linhas `prioridade = "todas"` aparecem as regras distintas das 3 prioridades, separadas por vírgula |
| `ganho_vs_ingenuo` | float | 0 % | `(1 − mae/mae_ingenuo) × 100`. Negativo = perde para o ingênuo |
| `supera_ingenuo` | bool | 0 % | `mae < mae_ingenuo`. Sempre `False` nas linhas do próprio ingênuo |

Sem a coluna `regra_ingenua`, um `mae_ingenuo` de D+7 não diz contra o que o modelo está correndo
— e as duas regras diferem em até 17 % de MAE.

`mase` e `ganho_vs_ingenuo` medem coisas próximas mas não idênticas: o `mase` compara com o
ingênuo **no treino** (referência estável), o `ganho_vs_ingenuo` com o ingênuo **no teste**
(mesmas datas). Divergência entre os dois é informação — significa que o período de teste foi mais
fácil ou mais difícil que o treino para uma previsão ingênua.

### Desenho e escolha

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `serie_modelada` | str | 0 % | **Nova.** Contra que série o modelo foi ajustado: `abertos` (D+1) ou `soma7` (D+7) |
| `usa_exogenas` | bool | 0 % | **Nova.** `True` para o LSTM, o único candidato que recebe o bloco de 10 features exógenas |
| `complexidade` | int | 0 % | 1 = ARIMA, 2 = SARIMA, 3 = Prophet, 4 = LSTM, 0 = ingênuo. É o critério de desempate |
| `escolhido` | bool | 0 % | Vencedor do grupo × horizonte. Uma linha `True` por combinação, sempre em `prioridade = "todas"` |

**Regra de escolha**, nesta ordem: (1) candidatos são os 4 modelos — o ingênuo **não concorre**;
(2) menor MAE na leitura geral; (3) empate técnico (diferença de MAE < 5 %) resolvido pelo **menos
complexo**; (4) se o vencedor perder para o ingênuo, isso é **registrado com destaque** e a
escolha se mantém, mas a leitura de negócio muda.

O passo (3) foi acionado em 2 dos 6 casos, os dois em D+7: `com_intervencao` (ARIMA no lugar do
SARIMA) e `sem_intervencao` (ARIMA no lugar do SARIMA).

---

# g_comparacao_grao.csv

**Grão:** `horizonte × prioridade` · **Chave:** as 2 colunas · **8 linhas × 12 colunas**.

Responde à pergunta de desenho: para prever a **volumetria total** de uma prioridade, é melhor
somar dois modelos por tipo, ou treinar um modelo só sobre o total?

Os dois lados são medidos **nas mesmas datas** (a interseção das janelas de teste) e contra o
**mesmo valor real** — o notebook asserta que `real_com + real_sem` é idêntico ao real do grupo
`total`. Cada lado usa o modelo vencedor do seu próprio grupo.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `horizonte` | str | 0 % | `D+1`, `D+7` |
| `prioridade` | str | 0 % | `"todas"` (geral) ou `"2"`, `"3"`, `"4"` |
| `n` | int | 0 % | Pontos comparáveis (84 e 66 na leitura geral; 28 e 22 por prioridade) |
| `mae_soma_2_modelos` | float | 0 % | MAE de `previsto_com + previsto_sem` contra o real total |
| `mape_soma_2_modelos` | float | 0 % | MAPE da mesma soma |
| `mae_modelo_unico` | float | 0 % | MAE do modelo treinado sobre o total, sem o grão de tipo |
| `mape_modelo_unico` | float | 0 % | MAPE do modelo único |
| `vantagem_da_separacao` | float | 0 % | `(1 − mae_soma/mae_unico) × 100`. **Positivo = separar por tipo é melhor** |
| `modelo_com_intervencao` | str | 0 % | Vencedor usado no lado `com_intervencao` |
| `modelo_sem_intervencao` | str | 0 % | Vencedor usado no lado `sem_intervencao` |
| `modelo_total` | str | 0 % | Vencedor usado no lado do modelo único |
| `separacao_vence` | bool | 0 % | `vantagem_da_separacao > 0` |

### O resultado — e ele mudou de sinal em relação à versão anterior

| Horizonte | Soma de 2 modelos | Modelo único | Vantagem da separação |
|---|---|---|---|
| D+1 (geral) | 85,26 | **82,21** | **−3,7 %** |
| D+7 (geral) | **552,19** | 555,80 | **+0,7 %** |

A versão anterior reportava +11,3 % e +14,7 %, com a conclusão de que **separar por tipo
compensava nos dois horizontes**. Com o desenho novo e as janelas de teste maiores, a vantagem
praticamente desaparece: em D+1 o modelo único passa a vencer por 3,7 %, e em D+7 a separação
ganha por menos de 1 %, o que é ruído.

**Leitura honesta: esta tabela não sustenta mais uma recomendação em nenhuma direção.** Por
prioridade o quadro é misto — a separação vence com folga em P2 (+22,0 % em D+1, +35,1 % em D+7)
e perde em P3 nos dois horizontes. O que a mudança sugere é que boa parte do ganho anterior vinha
do tamanho pequeno da janela de teste, não do grão.

⚠️ **Ressalva de tamanho de amostra.** São 84 pontos em D+1 e 66 em D+7 — o dobro do que a versão
anterior tinha, e ainda assim indicativo, não conclusivo. A decisão de negócio de separar
`com_intervencao` de `sem_intervencao` continua se sustentando pelo lado da **interpretação** (são
dinâmicas diferentes, e a quebra de setembro está inteiramente numa delas); pelo lado da
**previsão**, o número não decide.

---

# g_ablacao_exogenas.csv

**Grão:** `tipo_tratamento × horizonte × medidor` · **Chave:** as 3 colunas · **8 linhas × 12
colunas**. Tabela **nova** nesta versão.

Ela existe por um motivo específico: é a **evidência que sustenta o desenho do treino**. Sem ela,
"os dois horizontes são treinados separados para poder usar exógenas" seria uma escolha de
arquitetura sem número em disco para justificá-la.

Duas medições diferentes convivem aqui, e a distinção é o ponto da tabela:

- **`XGBoost (§5.6)`** — mede quanto sinal **existe** nas exógenas, num modelo diagnóstico que não
  compete. Empilha as 9 séries, então tem `tipo_tratamento = "todos"`;
- **`LSTM (§7.7)`** — mede quanto sinal o modelo que **de fato compete** consegue extrair, grupo a
  grupo, comparando a mesma rede com e sem o bloco exógeno, pareado, em 8 sementes.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `tipo_tratamento` | str | 0 % | `com_intervencao`, `sem_intervencao`, `total`, ou `todos` (linhas do XGBoost) |
| `horizonte` | str | 0 % | `D+1`, `D+7` |
| `medidor` | str | 0 % | `XGBoost (§5.6)` ou `LSTM (§7.7)` |
| `n_origens` | int | 0 % | Pontos de teste da comparação |
| `mae_com_exogenas` | float | 0 % | MAE com o bloco exógeno |
| `mae_sem_exogenas` | float | 0 % | MAE sem ele |
| `delta_mae` | float | 0 % | `com − sem`. **Negativo = as exógenas ajudam** |
| `delta_pct` | float | 0 % | O mesmo em % de `mae_sem_exogenas` |
| `mae_ingenuo` | float | 0 % | O piso, para dar escala ao delta |
| `mde` | float | 50 % | **Efeito mínimo detectável** a 80 % de poder, já corrigido pela autocorrelação da sobreposição. Nulo nas linhas do XGBoost, que não têm o pareamento por origem |
| `acima_do_mde` | bool | 50 % | `abs(delta_mae) > mde`. **`False` significa "o teste não tem tamanho para decidir"**, não "as exógenas não servem" |
| `n_features_exogenas` | int | 0 % | 67 no painel do XGBoost, 10 no bloco pré-registrado do LSTM |

### O resultado

| Medidor | Horizonte | Grupo | Δ % | MDE | Veredito |
|---|---|---|---|---|---|
| XGBoost | D+1 | todos | −11,4 % | — | sinal presente |
| XGBoost | D+7 | todos | −13,7 % | — | sinal presente, e maior |
| LSTM | D+1 | com_intervencao | −1,8 % | 0,84 | dentro do ruído |
| LSTM | D+1 | sem_intervencao | −8,8 % | 12,04 | dentro do ruído |
| LSTM | D+1 | total | **−8,9 %** | 9,29 | **ajudam** |
| LSTM | D+7 | com_intervencao | −3,9 % | 9,76 | dentro do ruído |
| LSTM | D+7 | sem_intervencao | −0,5 % | 32,41 | dentro do ruído |
| LSTM | D+7 | total | +13,4 % | 86,58 | dentro do ruído |

**A leitura que importa: o sinal que o XGBoost mede não se converte em ganho mensurável no modelo
que compete.** Em 5 dos 6 cortes a diferença fica abaixo do efeito mínimo detectável. Isso é
compatível com duas explicações que a tabela não separa — o LSTM não extrai esse sinal com 87 a
316 amostras, ou o teste não tem tamanho para ver o ganho — e a coluna `mde` existe justamente
para impedir a terceira leitura, errada, de que "as exógenas não servem".

**Por que elas ficam no modelo mesmo assim.** Com previsão direta elas são admissíveis, §5.6
mostra que carregam sinal, e o custo de mantê-las quando não ajudam está medido e é pequeno. O que
esta camada **não** pode afirmar é que elas viram o jogo contra o piso ingênuo: para isso faltaria
histórico, não feature.
