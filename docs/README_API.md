# API de previsão de incidentes

Camada de serving dos 18 modelos vencedores de `models/` — 8 `SARIMAX` (`.pkl`), 7 `Theta` e
3 `ETS` (`.json`) — numa API REST e em duas páginas web:

- **Painel (`/`)** — os números principais de um dia, entre 01/09 e 31/12/2025: com e sem
  intervenção empilhados em dois gráficos (D+1 sobre os últimos 14 dias, D+7 sobre as últimas 4
  semanas) e a chance de quebra dos dois KPIs de OLA. Filtro de prioridade; `/?data=AAAA-MM-DD`
  abre direto numa data.
- **Detalhes (`/detalhe`)** — qualquer data do histórico: features de entrada, previsão dos três
  grupos com o selo da situação da data, valor real, desempenho contra o ingênuo, e os três
  painéis de negócio (risco de OLA, capacidade, dias atípicos).

O contrato dos modelos está em [`docs/CONTRATO_MODELOS.md`](CONTRATO_MODELOS.md). A visão geral do
projeto e o passo a passo que produz o dado que esta API lê estão no
[`README.md`](../README.md) da raiz.

---

## Subir

### Desenvolvimento — dado fora da imagem (bind mount)

```bash
docker compose up --build
```

Abre em **http://localhost:8000** (documentação interativa em `/docs`). Os artefatos de `models/`
(`.pkl` e `.json`) e as CSVs ficam
montados como somente-leitura a partir da própria árvore do repositório — retreinou no notebook?
Basta `docker compose restart`, sem rebuild.

### Entrega — imagem autocontida

```bash
docker build -t lw-previsao:1.0 .
docker run --rm -p 8000:8000 lw-previsao:1.0
```

A imagem (~535 MB, dos quais ~25 MB de dado) roda em qualquer máquina sem preparar pasta nenhuma.

### Sem container

```bash
./.venv/Scripts/python.exe -m pip install -r requirements_api_container.txt
./.venv/Scripts/python.exe -m uvicorn api.main:app --reload
```

---

## ⚠️ Como o dado entra no container

**Nada do que a API precisa está versionado.** O `.gitignore` do projeto exclui todas as CSVs das
camadas 0–3, todos os `.pkl` e todo `models/*.json` (ETS/Theta e os sidecars `.config.json`). Quem
clona o repositório recebe só código — e é por isso que existem os dois caminhos acima em vez de
um `git clone && docker build` que funcionaria em qualquer lugar.

Os ~25 MB que a API lê:

| Arquivo | Tamanho | Para quê |
|---|---|---|
| `models/` (18 artefatos `.pkl`/`.json` + sidecars + `manifesto.csv`) | 22 MB | os modelos e o que justifica cada um |
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
| `GET /` | o painel principal |
| `GET /detalhe` | a página de detalhes |
| `GET /docs` | OpenAPI interativo |
| `GET /api/painel?origem=` | **painel** — de `2025-09-01` a `2025-12-31`: para as 3 prioridades, as pilhas com/sem realizadas (diária e semanal), as previsões D+1 e D+7 de cada tipo, os KPIs de OLA e a etiqueta da data; memorizado por origem |
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
curl -s "localhost:8000/api/painel?origem=2025-12-20"
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

### Painel principal

**Datas.** Qualquer origem de 01/09 a 31/12/2025, o intervalo em que com e sem intervenção estão
os dois dentro da própria janela. Antes de 01/09 o modelo `sem_intervencao` só extrapolaria sobre
o regime pré-automação. Uma etiqueta discreta ao lado da data diz em que período ela cai:
**treino** (o modelo viu esses dias no ajuste, então o acerto é otimista), **teste**, **fronteira**
(embargo) ou **produção** (sem real para comparar, como em 31/12).

**Gráficos.** Com intervenção fica na base da pilha (é o que consome analista) e sem intervenção
em cima; a última barra, em tom claro, é a previsão. O D+1 aparece sobre os últimos 14 dias. O D+7
aparece sobre as últimas 4 semanas, cada barra sendo o `soma7` que fecha naquele dia, então a
semana prevista fica na mesma unidade das realizadas. Quando o período previsto já tem real, um
losango escuro marca o total realizado, e as fichas, o tooltip e a tabela o abrem em com e sem. A faixa de 80 % de cada modelo vai no tooltip e na tabela:
a faixa da soma não é a soma das faixas, então não é desenhada.

**O modelo `total` não está no painel.** A pilha prevista é a soma dos dois modelos por tipo, e o
número de destaque é essa soma. Mostrar também o modelo único poria dois "totais" que não batem
na mesma tela. Ele continua em `/detalhe`.

**Visão agregada ("Todas").** Não existe modelo para "todas as prioridades": gráficos e números
somam o realizado e as previsões das três prioridades (seis modelos: 2 tipos × 3 prioridades), e
a API devolve isso pronto em `prioridades.todas`. A faixa de 80 % não aparece na visão agregada,
porque a faixa de uma soma não é a soma das faixas. Os KPIs de OLA **não** são somados: as faixas
são calibradas por prioridade, e o cartão mostra as roscas de cada uma, uma embaixo da outra.

**KPIs.** O acumulado das regras de OLA é anual e zera em 01/01 (`api/ola.py::painel_kpis`):

- **ano corrente** — `painel()` até 31/12: chance de cair de faixa e data provável de cruzar o
  próximo corte. A perna do modelo é o D+7 quando os 7 dias cabem antes do fim do ano, e o D+1
  quando não cabem. Em 31/12 mostra o atingimento final (P2 duração 75 %, P3 125 %, volume 0 %
  com a faixa estourada);
- **ano novo no ritmo atual** — só quando a semana prevista atravessa 01/01 (origens de 25/12 em
  diante). O acumulado parte de zero; os dias do D+7 que caem em 2026 vêm do modelo (grupo
  `total`), e o resto do ano é a taxa de 28 dias mantida constante.

⚠️ O ano novo é um ano extrapolado a partir de dezembro, e por isso sai quase binário (0 % ou
100 %). A informação útil é a **data de cruzamento**: no volume, P2 e P3 cruzam o primeiro corte
entre o fim de fevereiro e março de 2026, porque as faixas de volume continuam descalibradas.

**Rosca.** Cada regra com meta ganha uma rosca. O anel é a escala de 0 a 150 %; o arco é o
atingimento do dia, na cor da faixa (azul acima da meta, verde em 100 %, laranja e vermelho
abaixo — tokens `--ola-*` de `marca.css`); o tracinho marca a meta de 100 %. O trecho entre a
faixa atual e a de baixo pulsa em vermelho, com intensidade proporcional à chance de perdê-lo até
31/12. Quem pede `prefers-reduced-motion` recebe o trecho sem animação.

**Como a chance de quebra é calculada** (`api/ola.py::painel`, Monte Carlo):

1. **hoje** — o acumulado anual da prioridade inteira (`s_fato_ola_prioridade`) e a faixa em que
   ele cai;
2. **taxas das últimas 28 dias** — fechados por aberto, violações por fechado, fechados por dia
   (média e desvio);
3. **perna do modelo** — a previsão D+7 do grupo `total` (D+1 quando os 7 dias não cabem até
   31/12), convertida em fechamentos. A incerteza sai da faixa de 80 % da previsão;
4. **perna da taxa** — os dias restantes até 31/12 à média diária, com desvio crescendo com a
   raiz do número de dias;
5. **2.000 sorteios** da soma das duas pernas, com semente fixa, para o número não oscilar entre
   recargas. Na regra de duração as violações entram como Poisson sobre os fechamentos. **A chance
   de quebra é a fração dos sorteios em que o acumulado cruza o corte e cai de faixa.** O risco é
   baixo abaixo de 20 %, moderado até 50 % e alto daí em diante;
6. **data provável de cruzamento** — o que falta até o corte dividido pela média diária.

O caso que valida o painel: em 20/12/2025 a P3 tinha 197 violações contra o corte de 201. O painel
dá 89 % de chance e cruzamento previsto em 26/12, e a P3 cruzou de fato em 26/12.

⚠️ Ponto em aberto: a perna do modelo usa o modelo `total`, não a soma com + sem que o painel
desenha. Os dois podem divergir.

**A marca de ingênuo não aparece no painel** (decisão da autora, 2026-09-10). A resposta de
`/api/painel` continua carregando o fato no bloco `avisos`, e a página de detalhes o mostra ao
lado de cada previsão.

**Marca — DDIP (data driven incident preventor).** "Dip" é mergulho: a logo é um mergulhador
numa rede neural, um mergulho nos dados da Locaweb. Cor, fonte, raio e sombra vivem só em
`api/web/marca.css`, sobre a paleta da apresentação: azuis `#01386A` · `#23496B` · `#3774AB`,
creme `#EEDED1` e cinza `#3A393F`.

- **Logo:** `api/web/marca/ddip.svg` é o traçado original (`logo.svg`, mantido intacto) recolorido:
  desenho creme `#EEDED1` sobre fundo `#01386A`. O fundo da logo é o mesmo marinho do topo, então
  ela se funde na faixa. `logo_png.png` fica como referência.
- **Fonte:** Aptos, com Segoe UI e a fonte do sistema como alternativas. A Aptos só aparece onde
  estiver instalada **no sistema operacional**; o cache de fontes de nuvem do Office não é
  visível para o navegador. O arquivo da fonte não vai na imagem porque a licença da Microsoft não
  deixa clara a redistribuição.
- **Modo claro e escuro:** claro com fundo creme e tinta cinza, escuro com fundo cinza e tinta
  creme. O botão do topo alterna e guarda a escolha no navegador; sem escolha, a página segue o
  tema do sistema. `api/web/tema.js` aplica o tema antes da primeira pintura, para não piscar, e
  avisa as páginas para redesenhar os gráficos, que guardam as cores de quando foram criados.
- **Cores com significado:** com intervenção em azul claro, sem intervenção em roxo e total em
  âmbar, uma ordem categórica validada contra daltonismo em cada tema. Roxo e azul se confundem na
  deuteranopia, e é a diferença de claridade que os separa. A rosca usa os azuis da marca acima
  da meta, verde na meta e laranja/vermelho abaixo. Ao mexer em qualquer cor de grupo,
  revalidar com o `validate_palette.js` nos dois temas.

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

**11 das 18 séries superam o baseline ingênuo**; as 7 que perdem se concentram em P3/P4 de
`sem_intervencao`/`total`. A página de detalhes mostra isso ao lado de cada previsão
(`✅ supera o ingênuo` / `❌ perde do ingênuo`), com o valor da regra ingênua na mesma linha. A
API devolve o mesmo fato no bloco `avisos` de toda rota, inclusive `/api/painel`. A exceção é o
painel principal, que não renderiza a marca (ver acima).

A recomendação registrada no projeto vale aqui: usar o modelo em produção onde ele ganha, e o
próprio ingênuo como referência operacional nos demais.

---

## Azure — monitoramento

Instrumentação opcional do Application Insights, ligada só por variável de ambiente (sem ela a
API sobe igual, como sempre subiu):

| Variável | Para quê | Se ausente |
|---|---|---|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | connection string do Application Insights | telemetria desligada |

Com a variável definida, `api/main.py` chama `configure_azure_monitor` no startup e passa a
instrumentar FastAPI, logging e requisições automaticamente. O provisionamento dos recursos na
Azure está em [`../azure/provisionar.sh`](../azure/provisionar.sh).

---

## Testes

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
```

| Arquivo | O que garante |
|---|---|
| `test_reproducao.py` | **portão de qualidade** — as 18 séries (534 origens de teste, as três famílias) replicadas contra `g_previsoes.csv` com tolerância de 0,011; também a identidade `soma7(D+7) = acumulado D+1..D+7` e `total = com + sem` |
| `test_classificacao.py` | os selos nas fronteiras exatas; 6 origens de embargo por série no D+7, nenhuma no D+1; contagem de origens de teste batendo com a cobertura da gold |
| `test_ola.py` | o atingimento calculado reproduz `s_fato_ola_prioridade` dia a dia; P4 sem meta; faixa de volume estourada sinalizada; o alerta de 15/12 caindo a ≤ 3 dias do cruzamento real |
| `test_painel.py` | a rota do painel: intervalo de datas aceito (01/09 a 31/12), pilha prevista = soma dos dois modelos, semana prevista emendando na última realizada, etiqueta treino/teste/produção, bloco de ano novo só na virada |

A reprodução passa por `prev.prever()`, a mesma função que as rotas HTTP chamam. As rotas em si
foram exercitadas com o `TestClient` do FastAPI: `/health` com 18 modelos, `/api/painel` nas duas
origens, 422 para origem fora do painel, e as rotas da página de detalhes.
