# API de previsão de incidentes

Camada de serving dos 18 modelos vencedores de `models/`: uma API REST e uma página web que
recebem *data + prioridade + horizonte* e devolvem as features de entrada, a previsão dos três
grupos, o valor real quando existe, e três painéis de negócio (risco de OLA, capacidade, dias
atípicos).

O contrato dos modelos está em [`docs/CONTRATO_MODELOS.md`](CONTRATO_MODELOS.md). A visão geral do
projeto e o passo a passo que produz o dado que esta API lê estão no
[`README.md`](../README.md) da raiz.

---

## Subir

### Desenvolvimento — dado fora da imagem (bind mount)

```bash
docker compose up --build
```

Abre em **http://localhost:8000** (documentação interativa em `/docs`). Os `.pkl` e as CSVs ficam
montados como somente-leitura a partir da própria árvore do repositório — retreinou no notebook?
Basta `docker compose restart`, sem rebuild.

### Entrega — imagem autocontida

```bash
docker build -t lw-previsao:1.0 .
docker run --rm -p 8000:8000 lw-previsao:1.0
```

A imagem (~530 MB, dos quais ~19 MB de dado) roda em qualquer máquina sem preparar pasta nenhuma.

### Sem container

```bash
./.venv/Scripts/python.exe -m pip install -r requirements_api_container.txt
./.venv/Scripts/python.exe -m uvicorn api.main:app --reload
```

---

## ⚠️ Como o dado entra no container

**Nada do que a API precisa está versionado.** O `.gitignore` do projeto exclui todas as CSVs das
camadas 0–3 e todos os `.pkl` (`*.pkl`). Quem clona o repositório recebe só código — e é por isso
que existem os dois caminhos acima em vez de um `git clone && docker build` que funcionaria em
qualquer lugar.

Os 19 MB que a API lê:

| Arquivo | Tamanho | Para quê |
|---|---|---|
| `models/` (18 `.pkl` + `manifesto.csv`) | 17 MB | os modelos e o que justifica cada um |
| `2_silver_data/s_fato_diario_prioridade.csv` | 1,5 MB | a série e as features |
| `2_silver_data/s_dim_calendario.csv` | 210 KB | calendário, inclusive 2026 (exógena futura) |
| `2_silver_data/s_fato_ola_prioridade.csv` | 113 KB | acumulado anual e atingimento de OLA |
| `2_silver_data/s_fato_diario_prioridade_turno.csv` | 1,2 MB | distribuição por turno (capacidade) |
| `3_gold_data/g_previsoes.csv` | 164 KB | conferência do selo `TESTE` |
| `3_gold_data/g_avaliacao_modelos.csv` | 15 KB | métricas por corte |

O `.dockerignore` mantém `.venv/`, `notebooks/` (8 MB), `0_raw_data/` e `1_bronze_data/` fora do
contexto de build. Os caminhos são configuráveis por variável de ambiente — `CAMINHO_MODELOS`,
`CAMINHO_SILVER`, `CAMINHO_GOLD`.

**Pins de versão não são zelo.** Os artefatos são pickle de statsmodels: a versão que desserializa
precisa casar com a que serializou. `requirements_api_container.txt` fixa exatamente o ambiente de
treino (as mesmas versões de núcleo de `requirements_notebooks.txt`), e
`/health` devolve as versões carregadas para que uma incompatibilidade apareça como diagnóstico e
não como erro 500 no meio de uma demonstração.

---

## Rotas

| Rota | O que devolve |
|---|---|
| `GET /` | a página |
| `GET /docs` | OpenAPI interativo |
| `GET /health` | modelos carregados, séries montadas, versões |
| `GET /api/catalogo` | datas válidas, janelas, cortes, regimes, o manifesto inteiro |
| `GET /api/features?data=&prioridade=&horizonte=` | todas as features de entrada do dia, por grupo |
| `GET /api/previsao?data=&prioridade=&horizonte=` | **principal** — os 3 grupos + a soma dos dois |
| `GET /api/risco-ola?data=&prioridade=&horizonte=&ate=` | painel de OLA |
| `GET /api/capacidade?data=&prioridade=&horizonte=&jornada_h=&ocupacao=&fator_esforco=` | painel de capacidade |
| `GET /api/atipicos?inicio=&fim=&prioridade=&grupo=&alfa=` | dias com o real fora da banda |

Toda resposta carrega um bloco `avisos`. As ressalvas do projeto não vivem só no HTML: quem
consumir a API por outro caminho as recebe junto com o número.

```bash
curl -s localhost:8000/health
curl -s "localhost:8000/api/previsao?data=2025-12-15&prioridade=3&horizonte=D%2B7"
curl -s "localhost:8000/api/risco-ola?data=2025-12-15&prioridade=3"
curl -s "localhost:8000/api/atipicos?inicio=2025-11-20&fim=2025-12-31&prioridade=2"
```

---

## A situação da data — o que a tela existe para deixar claro

Para cada grupo e horizonte, a data de origem recebe um selo. Os três cards podem mostrar selos
diferentes na mesma data, porque `com_intervencao` tem janela e corte próprios: isso é
informação, não inconsistência.

| Selo | Quando | Prevê? | Tem real? |
|---|---|---|---|
| `TREINO` | o alvo inteiro cabe antes do corte | ✅ in-sample — acurácia otimista por construção | ✅ |
| `EMBARGO` | a origem é anterior ao corte, mas a janela-alvo invade o teste | ✅ | ✅ |
| `TESTE` | out-of-sample; é a leitura que `g_previsoes.csv` guarda | ✅ | ✅ |
| `SEM RESPOSTA` | as features existem, o alvo cairia depois do fim da série | ✅ | ❌ é o caso de uso em produção |
| `FORA DA JANELA` | a data antecede a janela do grupo | ⚠️ extrapolação | ✅ mas o modelo nunca viu esse regime |
| `SEM FEATURES` | fora de 2023-01-02 … 2025-12-31 | ❌ | ❌ |

`EMBARGO` é o *purged split*: no D+7 são exatamente 6 origens por série, as que teriam alvo
cobrindo dias de teste. Não foram amostra de treino nem ponto de avaliação.

Datas para percorrer os quatro casos (P3, D+7): `2025-11-10` treino · `2025-11-15` embargo em
`com_intervencao` e treino nos outros dois · `2025-12-15` teste · `2025-12-28` sem resposta ·
`2025-05-10` fora da janela em `sem_intervencao`/`total`.

---

## Os painéis

### Risco de cumprimento de OLA

Acumulado anual da **prioridade inteira** (as duas fatias somadas), projetado até o fim do ano por
Monte Carlo em duas pernas: a previsão do modelo cobre os próximos 1 ou 7 dias, o resto é
extrapolação da taxa diária recente. Devolve faixa atual, orçamento restante até o próximo corte,
data provável de cruzamento e probabilidade de cair de faixa.

São **dois cenários** lado a lado: taxa de 28 dias e taxa de 7 dias. A janela longa achata o
começo de uma escalada, que é justamente quando o alerta precisaria sair — e mostrar a
discordância entre as duas leituras é mais útil do que escolher uma.

**O caso que dá razão ao painel:** em 15/12/2025 a P3 tinha 189 violações acumuladas e 12 de folga
até o corte 201. O cenário de 28 dias dava 5 % de risco; o de 7 dias dava 81 % e projetava o
cruzamento em **27/12**. A P3 cruzou em **26/12** e caiu de 150 % para 125 %.

Três ressalvas que o painel mostra em vez de esconder:

- **as faixas de volume estão estouradas** — P2 fechou 15.649 no ano contra um corte máximo de
  6.337, P3 fechou 41.732 contra 24.277. O atingimento é 0 % o ano inteiro e não há gradiente de
  risco. As faixas foram calibradas para outra escala e precisam de recalibração;
- **P4 não tem meta** em nenhuma das duas regras — o painel diz isso, não inventa número;
- **só a primeira perna vem de modelo.** O resto é extrapolação de taxa, e está rotulado.

### Capacidade

Só a fatia `com_intervencao` — o que fecha sozinho no monitoramento não consome analista.
Incidentes previstos × `duracao_mediana_h` × `fator_esforco` ÷ (jornada × ocupação), distribuídos
pelo share histórico de turno.

⚠️ `duracao_mediana_h` é **tempo decorrido até o fechamento**, não esforço em mãos. É por isso que
`fator_esforco` é parâmetro (`?fator_esforco=0.4`) e vem com o aviso: o número só vira
dimensionamento depois que a área calibrar esse fator uma vez.

### Dias atípicos

Varre um intervalo prevendo cada dia a partir da véspera e marca os que caíram fora da banda de
95 %, enriquecidos com a leitura de concentração (`inc_por_ic` contra a mediana móvel de 90 dias):
poucos ICs concentrando volume = evento **sistêmico**; volume espalhado = operação normal em
escala.

Vale mesmo onde o modelo perde para o ingênuo: aqui não importa acertar o ponto, importa ter a
**banda calibrada**. Em P2 `com_intervencao`, no período de teste, saem 4 dias fora contra ~2,1
esperados por acaso — 3 deles com marca de sistêmico.

---

## Honestidade sobre o que os modelos entregam

**1 de 6 cortes supera o baseline ingênuo** — só `com_intervencao` em D+7 (+36,7 % de MAE). Nos
outros cinco a regra ingênua erra menos que o modelo. A tela mostra isso ao lado de cada previsão
(`✅ supera o ingênuo` / `❌ perde do ingênuo`) e a API devolve no bloco `avisos`, com o valor da
regra ingênua na mesma linha da previsão para comparação direta.

A recomendação registrada no projeto vale aqui: usar o modelo em produção onde ele ganha, e o
próprio ingênuo como referência operacional nos demais.

---

## Testes

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
```

| Arquivo | O que garante |
|---|---|
| `test_reproducao.py` | **portão de qualidade** — as 18 combinações replicadas contra `g_previsoes.csv`; também a identidade `soma7(D+7) = acumulado D+1..D+7` e `total = com + sem` |
| `test_classificacao.py` | os selos nas fronteiras exatas; 6 origens de embargo por série no D+7, nenhuma no D+1; contagem de origens de teste batendo com a cobertura da gold |
| `test_ola.py` | o atingimento calculado reproduz `s_fato_ola_prioridade` dia a dia; P4 sem meta; faixa de volume estourada sinalizada; o alerta de 15/12 caindo a ≤ 3 dias do cruzamento real |

**Reprodução verificada também pela HTTP, com o container de pé:** 534 origens de teste, as 18
combinações, **divergência máxima 0,00** contra a camada gold.
