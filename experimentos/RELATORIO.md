# Retreino — diagnóstico da safra atual e resultados do novo protocolo

Sessão de 2026-09-09. Objetivo: superar o baseline ingênuo, ou ao menos os vencedores atuais,
**sem criar nenhuma feature nova**. Tudo o que está aqui foi medido pelos scripts desta pasta.

---

## 1. Resumo

| | safra atual | novo |
|---|---|---|
| agregado (grupo × horizonte) que vence o ingênuo | **1 de 6** | **2 de 6** |
| agregado melhor que a safra atual | — | **5 de 6** |
| séries melhores que a safra atual | — | **13 de 18** |
| séries que vencem o piso ingênuo | 11 de 18 * | 10 de 18 |
| MAE somado no hold-out | 4.084 | **3.792** (−7,2 %) |
| MASE médio | — | 1,183 |
| MASE médio sem as 4 séries P3 quebradas | — | **0,787** |

\* **As 11 de 18 da safra atual não são comparáveis com as 10 de 18 novas.** A safra atual escolhe
o vencedor olhando o MAE do próprio conjunto de teste; aqui a escolha nunca vê o teste. Contar
vitórias favorece quem escolheu com a resposta na mão. O número comparável entre os dois
protocolos é o **MAE somado**, e ele caiu 7,2 %.

Agregado por grupo × horizonte (é o critério que o projeto reporta):

| grupo | horizonte | MAE novo | piso | ganho novo | MAE safra atual | ganho safra atual |
|---|---|---|---|---|---|---|
| com_intervencao | D+1 | **14,81** | 15,87 | **+6,7 %** | 16,21 | −2,2 % |
| sem_intervencao | D+1 | 56,31 | 54,13 | −4,0 % | 85,83 | −58,6 % |
| total | D+1 | 59,60 | 59,21 | −0,7 % | 82,21 | −38,8 % |
| com_intervencao | D+7 | 63,93 | 91,90 | **+30,4 %** | 58,20 | +36,7 % |
| sem_intervencao | D+7 | 547,65 | 458,86 | −19,3 % | 563,14 | −22,7 % |
| total | D+7 | 521,75 | 462,97 | −12,7 % | 555,80 | −20,1 % |

`com_intervencao D+1` era a falha emblemática (−2,2 %) e virou **+6,7 %**. `sem_intervencao D+1`
saiu de −58,6 % para −4,0 %, e `total D+1` de −38,8 % para −0,7 % — ainda perdem, mas por margem
que cabe no erro padrão. A única piora é `com_intervencao D+7`, e ela tem explicação na §6.

---

## 2. Diagnóstico da safra atual

### 2.1 O que estava certo e foi preservado

1. **Descartar o regime R1** (2023-01 a 2024-12, ~1 incidente/dia = artefato de extração). Sem
   isso nada funciona.
2. **Embargo das origens na fronteira** (`EMBARGO = passos - 1`). Correto e raro de ver.
3. **Dimensionar o teste por MDE a 80 % de poder.** A conclusão que ele produz — diferenças de
   2 a 5 % entre modelos são indistinguíveis — se confirmou repetidamente nesta sessão.
4. **Avaliação com origem expansiva e parâmetros congelados**, idêntica ao serving.
5. **Não usar o ranking de permutação para selecionar features** (ele é calculado no teste).
6. **Escolher a regra ingênua de D+7 por série** entre `soma7[D]` e `7×abertos[D]`.

### 2.2 Os erros, em ordem de custo

**1. `d` decidido por ADF (α = 0,05).** O teste devolveu `d = 0` para as **9 séries no D+1**,
inclusive as que crescem 5× no período. Resultado: modelos MA puros presos a uma constante —
`ARIMA(0,0,3)` tentando prever uma série que sai de ~100/dia para 273/dia. É a origem mecânica
dos MAE de 172 (contra 65 do ingênuo) e 1.193 (contra 745).

Ressalva de precisão: no **D+7** o ADF acertou `d = 1` em 6 das 9. O erro está concentrado no
horizonte curto — que é exatamente onde estão os piores resultados da safra.

Um teste isolado, antes de qualquer outra mudança, já mostrava o tamanho do problema:

| série (D+1) | MAE safra | com `log1p` | com grade em `d`/sazonal | ingênuo |
|---|---|---|---|---|
| com_intervencao P3 | 27,16 | 18,01 | **16,24** | 17,52 |
| sem_intervencao P2 | 25,11 | **18,46** | 24,46 | 27,96 |
| total P2 | 42,83 | **29,15** | 50,09 | 36,54 |
| total P3 | 147,27 | 146,76 | **81,19** | 71,43 |

**2. Nenhuma transformação de variância.** CV de 0,5 a 2,8 e caudas longas (P2 com_intervencao:
média 26, máximo 327). Ajustar em nível com erro gaussiano faz o MLE perseguir picos. `log1p`
sozinho corta 26 % do MAE em `total P2` e 27 % em `sem_intervencao P2`, e foi escolhido pela CV
em **13 das 18** séries na onda A.

**3. Seleção do vencedor no próprio conjunto de teste** (célula 97), com 4 candidatos, 28 a 42
pontos e tolerância de 5 %. A justificativa da célula 4 para dispensar backtest de origem móvel
("reusaria o mesmo dado finito") confunde duas coisas: o ganho da CV não é criar dado, é **deixar
de escolher no teste**.

**4. Escolha agregada em `prioridade='todas'`**, somando MAE de séries de 22 a 913 incidentes/dia.
Na prática P3 escolhe sozinha para todo mundo. `com_intervencao/P2/D+1/ARIMA` ganha +16,2 % e é
descartada porque o agregado impõe SARIMA, que perde 2,2 %.

**5. `TOLERANCIA = 0,05` + ordenação por `COMPLEXIDADE`** institucionaliza o underfit: dentro de
5 % sempre vence o mais simples. Em `com_intervencao/D+7` isso trocou SARIMA (55,89) por ARIMA
(58,20).

**6. Grade saturada na borda.** As 9 ordens do D+7 terminam em `q = 7`, que é exatamente
`Q_MAXIMO["D+7"]`. Ampliando para `q ≤ 9`, a CV escolhe `q = 9` em 5 séries — a grade estava
apertada mesmo. `D` sazonal era fixo em 0; com a busca livre, `D = 1` aparece nos vencedores de
`com_intervencao` P2 e P4 no D+1.

**7. `enforce_stationarity=False` sem filtro posterior.** Sem a restrição, o otimizador pode parar
num modelo com raiz explosiva: ele ajusta bem dentro da amostra e diverge ao extrapolar. Produziu
uma previsão de **4.163** numa série cujo máximo histórico é 660. Duas travas foram acrescentadas
(§3).

**8. Tuning inexistente fora de ARIMA/SARIMA.** Prophet com `changepoint_prior_scale = 0,05` fixo
e LSTM com hiperparâmetros fixos. A conclusão "Prophet e LSTM não servem" não estava estabelecida
— eles foram julgados sem julgamento. Com 94 dias de treino, porém, o LSTM dificilmente se
recupera, e ele não voltou a ser testado aqui.

**9. Threshold de ablação conservador demais.** O critério `|Δmae| > dp_semente + dp_base` exige
que o ganho supere a **soma** dos dois desvios, quando o teste correto é sobre a **diferença
pareada por semente**. Rejeita quase tudo por construção. **Respondendo à pergunta: sim, thresholds
rígidos derrubaram candidatas boas.**

**10. As features com ganho comprovado só chegavam ao modelo que perde.** As razões `inc_por_*`
tinham −4,8 % de MAE com t = −5,38 e entravam apenas pelo LSTM. Nenhum SARIMAX as recebia. Nesta
sessão elas entram e são escolhidas em 2 das 18 séries; o bloco de exógenas observadas como um
todo é escolhido em 8.

### 2.3 Colhemos bons períodos? Tínhamos dado suficiente?

- **`com_intervencao`: sim.** 323 dias de treino, teste de 42.
- **`sem_intervencao` e `total`: não, e não há conserto.** 94 dias de treino; a série não existe
  antes de 2025-09-01. É limitação de dado, não de modelagem.
- **O teste não é representativo do treino em nenhuma série.** `sem_intervencao P3` tem teste 5,8×
  o treino; `com_intervencao P3/P4` estão em queda (−11,9 e −4,0 por mês) enquanto o treino é
  estável. E o teste cai inteiro sobre **Natal e Ano Novo**. Isso favorece estruturalmente o
  ingênuo, que persegue o degrau, e pune modelos ajustados à média.
- **Cross-validation ajudou** — não por criar dado, mas por tirar a seleção de cima do teste e
  medir o erro em 2 a 3× mais origens.

### 2.4 Modelos diferentes por série? Sim, com evidência

Força da sazonalidade semanal (η² do dia-da-semana, medida no treino):

| série | η² | leitura |
|---|---|---|
| com_intervencao P3 | 0,49 | dominante |
| com_intervencao P4 | 0,17 | real |
| com_intervencao P2 | 0,07 | marginal |
| sem_intervencao P2 / P3 / P4 | 0,08 / 0,05 / 0,02 | **nula** (F < 2) |

Testar bloco sazonal uniformemente gastava orçamento onde não há sinal. O novo desenho só o testa
onde η² > 0,05 e só no D+1 — `soma7` cobre 7 dias consecutivos, logo sempre um de cada dia da
semana, e o ciclo não sobrevive à agregação.

O resultado confirma que a especialização era necessária: os 18 vencedores são **8 SARIMAX, 7 ETS
e 3 Theta**, e dentro dos SARIMAX metade usa `log1p` e metade não.

---

## 3. O que mudou

| mudança | onde | efeito medido |
|---|---|---|
| `d` e `D` buscados na CV, não pelo ADF | `onda_a.py` | ver §2.2 item 1 |
| transformação `log1p` como candidata | `candidatos.py` | escolhida em 13 de 18 na onda A |
| `q` até 9 no D+7 | `onda_a.py` | `q = 9` vence em 5 séries |
| bloco sazonal condicionado a η² > 0,05 | `onda_a.py` | −40 % de custo, sem perda |
| ETS amortecido e Theta na disputa | `onda_b.py` | 10 dos 18 vencedores |
| exógenas observadas em D, defasadas de h | `onda_c.py` | `sem_int P2 D+7`: CV 66,6 → 42,5 |
| CV de origem móvel multibloco | `protocolo.py` | seleção deixa de ver o teste |
| busca de ordem refeita dentro de cada bloco | `onda_a.py`, `onda_c.py` | fecha vazamento sutil |
| portão pareado na seleção de exógenas | `onda_c.py` | corrige `total P4 D+1`: CV 31 / teste 111 |
| trava de sanidade na previsão | `protocolo.py` | contém previsão de 4.163 |
| filtro de raiz explosiva | `candidatos.py` | preventivo; não acionou nos vencedores |
| escolha por série, não agregada | `final.py` | ver §1 |

**A mecânica das exógenas observadas** merece nota, porque é o que as torna legítimas. A coluna
`<c>_obs<h>` é `c` defasada de `h` dias. O SARIMAX pede a exógena em cada passo previsto (linhas
D+1..D+h); nessa forma, a linha D+k carrega o valor de `c` em D+k−h, que nunca é posterior a D.
Sem a defasagem, usar `backlog` para prever D+1 seria ler o backlog do próprio dia previsto.

---

## 4. Resultado final por série

Configuração vencedora de cada série (`resultados/final.csv`):

| grupo | prio | h | MAE novo | piso | ganho | MAE safra | receita |
|---|---|---|---|---|---|---|---|
| com_intervencao | 2 | D+1 | 20,47 | 22,79 | **+10,1 %** | 21,55 | SARIMAX(0,0,3) log1p + `vespera_feriado`, `cos_semana` |
| com_intervencao | 3 | D+1 | 17,43 | 17,52 | +0,5 % | 17,13 | ETS tendência amortecida + sazonal |
| com_intervencao | 4 | D+1 | 6,52 | 7,29 | **+10,5 %** | 9,96 | SARIMAX(2,1,3)(1,1,1,7) drift, log1p |
| sem_intervencao | 2 | D+1 | 24,20 | 27,96 | **+13,5 %** | 25,11 | Theta s=7, log1p |
| sem_intervencao | 3 | D+1 | 75,72 | 65,43 | −15,7 % | 171,99 | Theta s=7 |
| sem_intervencao | 4 | D+1 | 69,00 | 69,00 | 0,0 % | 60,40 | ETS tendência amortecida |
| total | 2 | D+1 | 28,47 | 36,54 | **+22,1 %** | 42,83 | ETS simples, log1p |
| total | 3 | D+1 | 80,66 | 71,43 | −12,9 % | 147,27 | Theta s=7 |
| total | 4 | D+1 | 69,68 | 69,68 | 0,0 % | 56,53 | ETS tendência amortecida |
| com_intervencao | 2 | D+7 | 65,91 | 148,83 | **+55,7 %** | 69,19 | SARIMAX(0,0,9) + `backlog_obs7` |
| com_intervencao | 3 | D+7 | 92,58 | 92,58 | 0,0 % | 73,93 | ETS simples |
| com_intervencao | 4 | D+7 | 33,29 | 34,28 | +2,9 % | 31,48 | SARIMAX(1,0,9) + 3 exógenas |
| sem_intervencao | 2 | D+7 | 72,02 | 100,23 | **+28,1 %** | 95,74 | SARIMAX(0,0,7) log1p + `descricoes_distintas_obs7` |
| sem_intervencao | 3 | D+7 | 1.188,51 | 745,14 | −59,5 % | 1.193,41 | SARIMAX(1,1,9) + `backlog_obs7` |
| sem_intervencao | 4 | D+7 | 382,41 | 531,23 | **+28,0 %** | 400,28 | ETS simples |
| total | 2 | D+7 | 134,97 | 121,73 | −10,9 % | 148,81 | SARIMAX(0,0,6) log1p |
| total | 3 | D+7 | 1.017,15 | 709,09 | −43,4 % | 1.038,60 | SARIMAX(0,1,9) + `inc_por_ic_obs7` |
| total | 4 | D+7 | 413,13 | 558,09 | **+26,0 %** | 479,98 | ETS simples |

---

## 5. O que foi testado e NÃO funcionou

Registrado porque negativo medido também é resultado, e evita que alguém refaça.

**Combinação de previsões.** Três variantes nas mesmas ondas — média dos 2/3/5 primeiros, mediana
dos 3/5, e mediana exigindo 3 membros — deram 9, 8 e 9 vitórias contra as 10 da seleção
individual, com MAE somado entre 3.933 e 4.213 contra 3.792. O que decidiu contra não foi a média:
foi o modo de falha. Um único membro divergente arrasta a combinação inteira — em `total P2 D+1` a
média dos cinco primeiros levou o MAE de 28 para 4.163, e mesmo com a trava de sanidade ainda para
123. A mediana resolve esse caso e cria outros. Somado o custo de servir vários artefatos por
série, não se paga. Código preservado em `final.py` sob `COMBINAR = False`.

**Reconciliação de baixo para cima** (`total` = `com` + `sem`, previsão a previsão). Vantagem de
CV sempre abaixo de 1,5 %, e nas duas vezes em que a rota foi trocada com base nela o hold-out
piorou (`total P3 D+7`: 1.017 → 1.134). Ficou desligada por uma margem exigida de 5 %, que nenhuma
série alcança. Medida isolada, ela chega a ajudar (`total P2 D+7`: 141 → 103), mas não de forma
identificável a priori.

**Regra de 1 erro-padrão para desempate.** Com a CV desta série o erro padrão do MAE chega a
metade do próprio MAE, então quase tudo empata e vence o mais barato — que acaba sendo uma
suavização exponencial sem tendência nem sazonalidade, ou seja, o ingênuo com outro nome. Em três
séries o MAE de teste ficou idêntico ao do piso. Substituída por argmin do MAE de CV, com
parcimônia só como desempate abaixo de 0,5 %.

---

## 6. O que continua perdendo, e por quê

**As 4 séries de P3 em `sem_intervencao` e `total`** respondem por praticamente todo o prejuízo
restante. Excluindo-as: **10 de 14 vencem o piso e o MASE médio é 0,787**.

A causa é uma quebra de nível **dentro da janela de teste**. `sem_intervencao P3` tem média de
109/dia em setembro, 100 em outubro, 104 em novembro e **273 em dezembro**. Não é tendência, é
degrau, e nada no histórico o antecipa — é evento operacional. Com o treino terminando em
2025-12-03, nenhum modelo estacionário, com deriva ou amortecido tem como acompanhar. O ingênuo
"último valor" persegue o degrau depois que ele acontece; um modelo ajustado ao nível anterior,
não. **Isso é limitação de dado e não deve ser apresentado de outro jeito.**

**`com_intervencao D+7` piorou** (58,20 → 63,93). Causa identificada: em P3 a CV elegeu uma
suavização exponencial simples por margem de 1,1 % sobre o SARIMAX, e no hold-out essa escolha
custou 25 %. É o desacordo CV/teste na sua forma mais pura — o bloco de validação (out-nov) pega
a série parada, o teste pega ela despencando (−11,9/mês). Restringir a disputa a SARIMAX levaria
esse agregado a **54,40**, melhor que a safra atual; foi a razão de eu recomendar a variante só
SARIMAX. Com todas as famílias liberadas, é o preço pago.

---

## 7. Porte para `notebooks/model_training.ipynb` — FEITO

O notebook foi editado nesta sessão (116 → 119 células). A edição foi aplicada diretamente sobre
o JSON, porque o `NotebookEdit` exige leitura integral do arquivo e o CLAUDE.md a proíbe (3,7 MB);
cada célula alvo foi conferida por uma âncora de conteúdo antes de ser tocada, para que um índice
errado falhasse alto em vez de sobrescrever a célula errada em silêncio.

**Validação.** As 119 células compilam e o `nbformat` lê o arquivo. Um teste de fumaça executou a
cadeia mínima do caminho novo (imports → dados → séries → split → protocolo → candidatos) no
namespace real do notebook e rodou a seleção completa em `sem_intervencao P2 D+7`. O notebook
reproduziu a mesma receita e o **mesmo MAE de hold-out, 72,02**, que `resultados/final.csv` — o
código portado e o experimento validado concordam.

**O notebook ainda não foi executado de ponta a ponta**: a seção 7 sozinha leva ~2 h (a busca de
famílias multibloco é ~3× a da safra 1), e rodá-la sobrescreve `3_gold_data/` e `models/`, que
não são versionados.

**Uma limitação declarada no próprio notebook:** Prophet e LSTM ficaram como referência medida no
hold-out, **fora da disputa da CV**. Pontuá-los sob a CV multibloco exigiria retreinar a rede por
bloco e triplicar os ajustes do Prophet. A disputa validada aqui foi entre SARIMAX, ETS e Theta.
Isso é uma restrição de custo, não uma conclusão sobre as duas famílias.

### O que mudou, célula a célula

| célula | mudança |
|---|---|
| **5** | Acrescentar `TRANSFORMACOES = ["nenhuma", "log1p"]`, `TENDENCIAS = [(0,"c"), (1,"n"), (1,"t")]`, `SAZONAIS = [(0,0,0),(1,0,1),(0,1,1),(1,1,1)]`, `LIMIAR_SAZONAL = 0.05`, `Q_MAXIMO = {"D+1": 3, "D+7": 9}`, `BLOCOS`/`TAMANHO_BLOCO` de `protocolo.py`, e a lista `FEATURES_OBSERVADAS`. |
| **nova, após 10** | `_acrescentar_defasadas` de `dados.py` — cria `<c>_obs1` e `<c>_obs7` com `shift(h).bfill()`. |
| **nova, após 12** | `blocos_cv`, `janela_ajuste`, `avaliar_multi` e `_vif_sobreposicao` de `protocolo.py`. |
| **60** | Remover `grau_diferenciacao` (ADF). `buscar_ordem` passa a receber `transformacao`, `d`, `trend`, `sazonal_estrutura` e a usar **AICc** (não AIC), com o guarda `p+q+P+Q+n_exog ≤ n/6`. |
| **61** | `ajustar_statsmodels` ganha `transformacao` (aplicar `log1p`, desfazer com `expm1` **sem** correção de Jensen — a métrica é MAE, cujo previsor ótimo é a mediana) e padronização das exógenas pela janela de ajuste. Acrescentar o filtro `_estavel` (raízes AR) e a trava `teto = 2·max(y[D−27..D]) + 10`. |
| **novas** | Classes `Ets` e `Theta` de `candidatos.py`, com a mesma interface `ajustar`/`prever`. |
| **58** | Ampliar `REGRAS` com `mesmo dia da semana passada`, `média das últimas 4 semanas` e `média móvel 7d` — endurece o piso, o que é honesto. Manter a regra da safra atual como piso de comparação para não quebrar a série histórica. |
| **nova** | Seleção progressiva de exógenas de `onda_c.py`, com o portão `melhora_significativa` (diferença pareada além do próprio erro padrão) e `MAX_EXOG = 3`. |
| **97** | Substituir `TOLERANCIA`/`COMPLEXIDADE` por argmin do MAE de **CV** por série, com desempate por parcimônia só abaixo de 0,5 %. A escolha deixa de olhar `prioridade == "todas"`. |
| **100** | `escolher_por_serie` deixa de ser diagnóstico e vira o caminho principal. |
| **115** | Manter a nomenclatura. Acrescentar ao `manifesto.csv` as colunas `familia`, `transformacao`, `mae_cv`, `exog`, `n_blocos_cv`. **`EXTENSAO` precisa cobrir ETS e Theta** — ver abaixo. |
| **gráficos** | Manter os painéis de teste que já existem e acrescentar o de série inteira, com o aviso de dentro/fora da amostra escrito na figura. Portar `serie_completa` e `painel` de `graficos.py` — ver §11. |
| **não portar** | O deslocamento por quantil de §9 não entra: foi medido e não se paga. Vale portar só o acompanhamento da **taxa de subestimação por série**, que é o gatilho de retreino. |

### Serving: o contrato muda

Dos 18 vencedores, 10 não são `SARIMAXResults`. `docs/CONTRATO_MODELOS.md` §7 e `api/` precisam de:

- **ETS** — `statsmodels.tsa.exponential_smoothing.ets.ETSResults`, salvo com `.save()`. Servir com
  `ETSModel(historico, ...).smooth(params).forecast(passos)[-1]`, mesma lógica de refiltragem.
- **Theta** — não tem estado a congelar; é fechado e reajusta a cada origem. O artefato é só a
  configuração (`period`, `deseasonalize`, `transformacao`), então um JSON basta.
- **Transformação** — o serving precisa aplicar `log1p` antes e `expm1` depois, por artefato. É a
  mudança mais fácil de esquecer e a que mais estraga se esquecida.
- **Trava de sanidade** — replicar no endpoint, não só no treino.

`requirements_api_container.txt` não muda: ETS e Theta já vêm no statsmodels que está pinado.

---

## 8. Como rodar

```bash
cd experimentos
../.venv/Scripts/python.exe sanidade.py   # prova que a infra reproduz a safra atual (<0,3 %)
../.venv/Scripts/python.exe onda_a.py     # ~12 min — estrutura do ajuste
../.venv/Scripts/python.exe onda_b.py     # ~20 s  — ETS e Theta
../.venv/Scripts/python.exe onda_c.py     # ~5 min — exógenas
../.venv/Scripts/python.exe final.py      # consolida e mede no hold-out

../.venv/Scripts/python.exe comparacao.py           # §10 — antigo x novo, pareado
../.venv/Scripts/python.exe assimetria.py           # §9  — calibração do IC, pinball
../.venv/Scripts/python.exe assimetria_decisao.py   # §9  — vale deslocar?
../.venv/Scripts/python.exe graficos.py             # §11 — figuras
```

`sanidade.py` é o guarda-corpo: ele refaz o candidato ARIMA da safra antiga com o motor novo e
compara com `3_gold_data/g_avaliacao_modelos.csv`. Reproduz 17 dos 18 valores com 4 casas decimais
(maior divergência 0,298 %). Se esse teste falhar depois de qualquer mudança, o motor está errado
e nenhum ganho medido depois vale.

Arquivos: `dados.py` (séries, réplica das células 5/8/10/12) · `protocolo.py` (CV, avaliação,
seleção) · `candidatos.py` (SARIMAX, ETS, Theta, pisos, busca de ordem) · `onda_a/b/c.py` ·
`consolidar.py` (utilitários de leitura e reconstrução, usados por `final.py`) · `final.py` ·
`resultados/*.csv` (não versionado, já no `.gitignore`).

`onda_d.py` foi a primeira exploração de combinação e de reconciliação de baixo para cima, feita
sobre a CV de bloco único. Está superada por `final.py`, que faz as duas coisas sobre a CV
multibloco; fica na pasta como registro do caminho, não como etapa do fluxo.

Complementos: `assimetria.py` e `assimetria_decisao.py` (§9) · `comparacao.py` (§10) ·
`graficos.py` (§11).

---

## 9. Erro assimétrico — subestimar custa mais que superestimar

### Como a pergunta foi formalizada

O MAE é minimizado pela **mediana** da distribuição preditiva: por construção ele aceita errar
para baixo em metade dos dias. Se faltar custa `k` vezes mais que sobrar, o alvo ótimo passa a ser
o **quantil τ = k/(k+1)**, e a métrica correspondente é a perda pinball. Isso substitui uma margem
arbitrária por um botão contínuo: k = 2 → τ = 0,667; k = 3 → τ = 0,75; k = 5 → τ = 0,833.

O deslocamento aplicado é o quantil τ dos erros de validação, estimado **bloco-fora** (o bloco
avaliado nunca entra no cálculo do próprio deslocamento) e, para o hold-out, sobre todos os blocos.

### O resultado contraria a intuição — e é boa notícia

**Os modelos já erram para cima na maior parte dos dias.** Nas 14 séries sem quebra estrutural,
sem nenhum ajuste, apenas **31,3 % dos dias são subestimados**, e a sobra média por dia (70,9) é
**3,6 vezes** a falta média (19,9). O previsor mediano deveria dar ~50 %; ele dá 31 % porque as
séries caem no período de teste e os modelos ficam acima.

Por isso, deslocar para cima **piora** a perda pinball nessas 14 séries, em todos os níveis:

| k | política | pinball_k | MAE | % subestimado | falta/dia | sobra/dia |
|---|---|---|---|---|---|---|
| 2 | sem deslocamento | **36,87** | 90,76 | 31,3 % | 19,9 | 70,9 |
| 2 | deslocado | 42,01 (+13,9 %) | 112,03 (+23 %) | 24,0 % | 14,1 | 98,0 |
| 3 | sem deslocamento | **32,64** | 90,76 | 31,3 % | 19,9 | 70,9 |
| 3 | deslocado | 38,37 (+17,6 %) | 132,47 (+46 %) | 19,8 % | 10,5 | 122,0 |
| 5 | sem deslocamento | **28,40** | 90,76 | 31,3 % | 19,9 | 70,9 |
| 5 | deslocado | 32,00 (+12,7 %) | 159,41 (+76 %) | 14,8 % | 8,1 | 151,3 |

Ou seja: **mesmo julgando pela métrica que pune subestimação, não vale deslocar.** O preço em MAE
é alto (+46 % em k = 3) e a redução da falta não o compensa, porque a falta já era pequena.

Nas 18 séries o quadro se inverte em k = 5 (pinball −10 %), e a inversão vem inteiramente das duas
séries de P3 quebradas, onde **95 % dos dias são subestimados**. Lá o deslocamento ajuda muito —
mas isso é sintoma, não solução: o problema é o degrau de nível, e a resposta certa é detectá-lo,
não empurrar todas as previsões para cima o ano inteiro.

**Trocar de modelo sob pinball é pior ainda.** O vencedor muda em 12 de 18 séries quando a
seleção usa pinball em vez de MAE, mas aplicar essa troca piora a própria pinball em todos os `k`
(+3,5 % a +35,5 %). São trocas entre candidatos praticamente empatados — ruído de seleção. A
leitura correta é que, uma vez que o deslocamento recentra a previsão no quantil desejado, o que
resta para diferenciar modelos é a **dispersão** do erro, e é isso que o MAE já ordena.

### O intervalo de confiança é confiável?

Cobertura empírica dos intervalos analíticos do SARIMAX (média e erro padrão do próprio filtro de
Kalman; com `log1p` o intervalo é construído na escala transformada e trazido de volta com
`expm1`, o que é exato porque quantil é equivariante a transformação monótona):

| nominal | cobertura na CV | cobertura no teste | teste, sem as séries P3 quebradas |
|---|---|---|---|
| 80 % | 84,5 % | 66,3 % | **77,8 %** |
| 95 % | 94,1 % | 76,9 % | **89,7 %** |

**Resposta: sim, com ressalva.** Na validação o intervalo é bem calibrado (levemente conservador).
No hold-out ele fica um pouco estreito demais — 77,8 % onde promete 80 %, 89,7 % onde promete
95 % — o que é utilizável para dimensionamento operacional. O colapso da média geral vem das duas
séries quebradas, onde a cobertura de 80 % cai para **27,3 %** e **36,4 %**: exatamente as séries
em que o nível saltou. O intervalo mede a incerteza do processo que o modelo viu; ele não tem como
cobrir uma mudança de regime.

### Recomendação

Não aplicar deslocamento global. O ganho operacional está em **monitorar a taxa de subestimação
por série em produção** — se ela subir de forma sustentada acima de ~50 %, é sinal de degrau de
nível, e aí a ação é retreinar, não somar margem. O deslocamento por quantil fica disponível em
`assimetria.py` como botão por série, caso a operação queira aplicá-lo pontualmente onde a falta
doer mais.

---

## 10. Antigo × novo, série a série

Comparação **pareada nas mesmas datas-alvo** (Diebold-Mariano com erro padrão Newey-West, porque
no D+7 janelas consecutivas compartilham 6 dos 7 dias). Veredito: `SUBSTITUIR` se o novo é melhor
por mais de 1,64 erro padrão, `MANTER` se o antigo é, `INDIFERENTE` no meio — e no empate fica o
que já está em produção.

| grupo | prio | h | n | antigo | novo | MAE antigo | MAE novo | Δ % | t | veredito |
|---|---|---|---|---|---|---|---|---|---|---|
| com_intervencao | 2 | D+1 | 42 | SARIMA | SARIMAX | 21,55 | 20,47 | −5,0 | −0,86 | indiferente |
| com_intervencao | 3 | D+1 | 42 | SARIMA | ETS | 17,13 | 17,43 | +1,7 | 0,18 | indiferente |
| com_intervencao | 4 | D+1 | 42 | SARIMA | SARIMAX | 9,96 | **6,52** | −34,5 | −2,77 | **SUBSTITUIR** |
| sem_intervencao | 2 | D+1 | 28 | ARIMA | Theta | 25,11 | 24,20 | −3,7 | −0,35 | indiferente |
| sem_intervencao | 3 | D+1 | 28 | ARIMA | Theta | 171,99 | **75,72** | −56,0 | −4,21 | **SUBSTITUIR** |
| sem_intervencao | 4 | D+1 | 28 | ARIMA | ETS | 60,40 | 69,00 | +14,3 | 1,27 | indiferente |
| total | 2 | D+1 | 28 | ARIMA | ETS | 42,83 | **28,47** | −33,5 | −5,24 | **SUBSTITUIR** |
| total | 3 | D+1 | 28 | ARIMA | Theta | 147,27 | **80,66** | −45,2 | −3,14 | **SUBSTITUIR** |
| total | 4 | D+1 | 28 | ARIMA | ETS | 56,53 | 69,68 | +23,3 | 1,73 | **MANTER** |
| com_intervencao | 2 | D+7 | 36 | ARIMA | SARIMAX | 69,19 | 65,91 | −4,7 | −1,02 | indiferente |
| com_intervencao | 3 | D+7 | 36 | ARIMA | ETS | 73,94 | 92,58 | +25,2 | 1,31 | indiferente |
| com_intervencao | 4 | D+7 | 36 | ARIMA | SARIMAX | 31,48 | 33,29 | +5,7 | 1,99 | **MANTER** |
| sem_intervencao | 2 | D+7 | 22 | ARIMA | SARIMAX | 95,74 | **72,02** | −24,8 | −2,92 | **SUBSTITUIR** |
| sem_intervencao | 3 | D+7 | 22 | ARIMA | SARIMAX | 1193,41 | 1188,51 | −0,4 | −0,75 | indiferente |
| sem_intervencao | 4 | D+7 | 22 | ARIMA | ETS | 400,28 | 382,41 | −4,5 | −0,44 | indiferente |
| total | 2 | D+7 | 22 | ARIMA | SARIMAX | 148,81 | **134,97** | −9,3 | −4,01 | **SUBSTITUIR** |
| total | 3 | D+7 | 22 | ARIMA | SARIMAX | 1038,60 | 1017,15 | −2,1 | −1,57 | indiferente |
| total | 4 | D+7 | 22 | ARIMA | ETS | 479,98 | 413,13 | −13,9 | −0,34 | indiferente |

**SUBSTITUIR 6 · MANTER 2 · INDIFERENTE 10.**

| carteira | MAE somado |
|---|---|
| tudo antigo | 4.084 |
| tudo novo | 3.792 |
| **trocar em tudo menos nas 2 séries `MANTER`** | **3.777** |
| trocar só nas 6 séries `SUBSTITUIR` | 3.866 |

A recomendação é **trocar em tudo exceto `total P4 D+1` e `com_intervencao P4 D+7`**, onde o
modelo antigo é melhor com significância. Nas 10 séries `INDIFERENTE` o novo é melhor na média
mas dentro do ruído; trocar nelas é seguro e sai um pouco melhor (3.777 contra 3.866), e mantém
uma safra coerente em vez de metade de cada.

### Armadilha encontrada em `g_previsoes.csv`

A coluna `data` **não significa a mesma coisa nos dois horizontes**: no D+1 é a data-alvo
(`valor_real == abertos[data]`, confere em 42 de 42) e no D+7 é a data de **origem**
(`valor_real == soma7[data + 7d]`, confere em 36 de 36). Casar essa tabela com outra por `data`
sem corrigir descarta 7 dias por série no D+7 — e descarta justamente os primeiros, enviesando a
comparação. Na primeira versão desta análise isso produziu um MAE antigo de 27,46 para
`com_intervencao P3 D+7` quando o valor correto é 73,94. Vale corrigir o dicionário da camada
gold, ou renomear para `data_origem` / `data_alvo`.

---

## 11. Gráficos: real × previsto

`graficos.py` gera 6 figuras em `resultados/figuras/`, uma por grupo × horizonte, com três linhas
(P2/P3/P4) e dois painéis cada:

- **esquerda — a série inteira**, com a região de teste sombreada. Serve para a pergunta que o
  hold-out de 22 a 42 dias sobre o Natal não responde: o modelo acompanha o nível, o ritmo e a
  sazonalidade do histórico, ou só acertou (ou errou) um mês atípico?
- **direita — só o teste**, com o piso ingênuo e o modelo da safra anterior por cima.

**Ressalva obrigatória, e ela está escrita dentro da figura:** no painel esquerdo, antes da faixa
sombreada, os parâmetros já foram estimados naquele período — ali a previsão é **dentro da
amostra**. Leia nível e ritmo, não acurácia. Só a faixa sombreada é fora da amostra. Um gráfico
que mistura as duas coisas sem dizer qual é qual engana exatamente quem não leu o código.

Detalhe de implementação que custou um bug: `avaliar` estima os parâmetros na primeira origem que
recebe. Ao pedir a série inteira, isso ajustava o modelo em 31 pontos e um SARIMAX sazonal
degenerava para previsão zero. O parâmetro `n_ajuste` existe para fixar a janela no treino.

O que as figuras mostram e as tabelas não:

- **`com_intervencao P4 D+1`** — a safra anterior fica sistematicamente **acima** do real durante
  todo o teste, enquanto o modelo novo acompanha. É a leitura visual dos −34,5 % de MAE.
- **`com_intervencao P3 D+1`** — o ciclo semanal é reproduzido fielmente no histórico inteiro, o
  que confirma que o η² de 0,49 é sinal e não artefato.
- **`sem_intervencao P3 D+7`** — a prova visual da quebra estrutural: a série fica plana em torno
  de 800 durante todo o treino e sobe para 3.200 em dezembro. O modelo permanece plano porque é
  tudo o que ele viu; o ingênuo só alcança o novo nível correndo atrás dele. Nenhuma escolha de
  família ou hiperparâmetro muda isso.
- **`sem_intervencao P2 D+7`** — a previsão é quase uma reta em ~350 enquanto o real oscila entre
  160 e 950. Série sem sinal explorável; o modelo acerta a média e nada mais.

Para o notebook: manter os gráficos de teste que já existem e acrescentar o painel de série
inteira, reaproveitando `serie_completa` e `painel` de `graficos.py`. As duas funções não dependem
de nada da pasta `experimentos` além de `avaliar` e `SERIES`.
