# Dicionário de dados — Silver

Saída da Seção 4 de `notebooks/data_exploration.ipynb`. São 17 tabelas escritas por `salvar()`,
que valida o contrato antes de gravar: a chave declarada no `CATALOGO` precisa existir, ser única
e não ter nulo.

**Formato de todos os arquivos:** CSV, separador `;`, encoding `utf-8-sig`, sem índice.
Colunas de data são strings ISO `YYYY-MM-DD` (sem hora, sem fuso).

---

## Índice das tabelas

| Arquivo | Grão / chave | Linhas × colunas | Para quê |
|---|---|---|---|
| [`s_fato_diario_prioridade`](#s_fato_diario_prioridadecsv) | data × prioridade × tipo_tratamento | 6.570 × 56 | **Tabela principal.** As 6 séries alvo, suas features e os alvos |
| [`s_fato_ola_prioridade`](#s_fato_ola_prioridadecsv) | data × prioridade | 3.285 × 9 | Acumulado anual e atingimento de OLA |
| [`s_fato_diario_prioridade_turno`](#s_fato_diario_prioridade_turnocsv) | data × prioridade × tipo_tratamento × turno | 26.280 × 7 | Sazonalidade intradiária |
| [`s_fato_diario`](#s_fato_diariocsv) | data | 1.095 × 43 | Contexto do dia + calendário |
| [`s_fato_diario_time`](#s_fato_diario_timecsv) | data × time × tipo_tratamento | 37.230 × 8 | Carga por grupo designado |
| [`s_fato_diario_classe`](#s_fato_diario_classecsv) | data × classe_descricao × tipo_tratamento | 24.090 × 8 | Volume por tipo de alerta |
| [`s_ft_ic`](#s_ft_iccsv) | data | 1.095 × 14 | Features de item de configuração |
| [`s_ft_concentracao`](#s_ft_concentracaocsv) | data | 1.095 × 4 | Concentração da carga entre times (HHI) |
| [`s_ft_concentracao_tipo`](#s_ft_concentracao_tipocsv) | data × tipo_tratamento | 2.190 × 5 | A mesma concentração, dentro de cada série |
| [`s_ft_classe`](#s_ft_classecsv) | data × tipo_tratamento | 2.190 × 6 | Diversidade e concentração das classes de alerta |
| [`s_ft_texto`](#s_ft_textocsv) | data × prioridade × tipo_tratamento | 6.570 × 14 | Frequency encoding de template de descrição e de time |
| [`s_dim_calendario`](#s_dim_calendariocsv) | data | 1.460 × 23 | Calendário e sazonalidade — **1 ano além dos dados** |
| [`s_dim_ic`](#s_dim_iccsv) | ic | 9.171 × 18 | Perfil consolidado do item de configuração |
| [`s_dim_ic_regime`](#s_dim_ic_regimecsv) | ic × regime | 11.805 × 20 | Perfil do IC dentro de cada regime |
| [`s_dim_time_regime`](#s_dim_time_regimecsv) | time × regime | 48 × 25 | Perfil do time dentro de cada regime |
| [`s_dim_template`](#s_dim_templatecsv) | template_descricao | 13.317 × 22 | Perfil do template de alerta |
| [`s_tabela_modelo`](#s_tabela_modelocsv) | data (formato largo) | 365 × 392 | Matriz pronta para modelagem |

---

## Convenções que atravessam todas as tabelas

**Nomenclatura.** `snake_case` em tudo. Prefixos: `inc_` contagem de incidentes ·
`taxa_` / `pct_` percentual em escala 0–100 · `ac_` acumulado que zera na virada do período ·
`ic_` item de configuração · `y_` variável alvo.

**Uma dimensão é uma linha.** Prioridade, tipo de tratamento, turno, time e classe entram como
linha, nunca como colunas paralelas. O formato largo existe uma única vez, em `s_tabela_modelo`.

**Grade completa.** Toda tabela de série temporal cobre o intervalo diário inteiro
(2023-01-02 a 2025-12-31, 1.095 dias) × todas as combinações das dimensões. Dia sem evento é
linha com **zero**, não linha ausente — sem isso `rolling(7)` somaria 7 registros em vez de 7 dias.

**Zero contra nulo.** Contagens ausentes são preenchidas com 0 (o evento não ocorreu). Métricas
contínuas — medianas, percentis, taxas — ficam **nulas**, porque significam "não houve base de
cálculo", não "valor zero".

### `regime` — presente em quase todas as tabelas

| Valor | Período | Dias | Incidentes | Média/dia | Leitura |
|---|---|---|---|---|---|
| `1` | até 2024-12-31 | 730 | 732 (0,6 %) | 1,0 | **R1, artefato de extração.** Descartar da modelagem |
| `2` | 2025-01-01 a 2025-09-02 | 245 | 30.415 (24,8 %) | 124,1 | R2, pré-automação |
| `3` | a partir de 2025-09-03 | 120 | 91.396 (74,6 %) | 761,6 | R3, pós-automação |

Os cortes são as constantes `Q_R2 = 2025-01-01` e `Q_R3 = 2025-09-03` de §1.3.

### `tipo_tratamento` — a dimensão que define o alvo

| Valor | Origem (`Status` da bronze) | Incidentes |
|---|---|---|
| `sem_intervencao` | `Sem Intervenção` | 80.373 |
| `com_intervencao` | `Encerrado Automaticamente`, `Encerrado`, `Aguardando Problema` | 42.170 |

`Encerrado Automaticamente` **não** é ticket sem toque humano: é chamado tratado que o fluxo
fechou sozinho depois. Só `Sem Intervenção` é alerta que nasce e morre na máquina.

Média diária por tipo (P2–P4):

| Série | R2 (245 dias) | R3 (120 dias) | Fator |
|---|---|---|---|
| Com intervenção | 115,2 /dia | 107,4 /dia | **0,93×** |
| Sem intervenção | 7,7 /dia | 654,1 /dia | 85× |

A quebra de setembro está **inteiramente** na série sem intervenção. Consequência prática para
quem for modelar: as três séries `com_intervencao` dispõem de ~365 dias de histórico; as três
`sem_intervencao`, de ~120 — antes disso elas não existiam (97–99 % de dias zerados em R2).

---

# s_fato_diario_prioridade.csv

**Grão:** `data × prioridade × tipo_tratamento` · **Chave:** `data + prioridade + tipo_tratamento`
· **6.570 linhas × 56 colunas** (1.095 dias × 3 prioridades × 2 tipos).

Tabela principal do projeto. Contém as 6 séries alvo, suas features de janela e os 3 alvos por
série. Só prioridades 2, 3 e 4 — P1 e P5 são residuais e ficam em `s_fato_diario`.

### Chave

| Coluna | Tipo | Nulo | Domínio |
|---|---|---|---|
| `data` | date | 0 % | 2023-01-02 a 2025-12-31 |
| `prioridade` | int | 0 % | 2, 3, 4 |
| `tipo_tratamento` | str | 0 % | `com_intervencao`, `sem_intervencao` |

### Aberturas (contadas pela data de abertura)

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `abertos` | int | 0 % | **Base de todas as 6 séries alvo.** Incidentes abertos no dia. 0–913 |
| `abertos_monitoramento` | int | 0 % | Subconjunto com `Aberto por = Monitoramento` |
| `abertos_manual` | int | 0 % | Subconjunto com `Aberto por = Manual` |
| `abertos_hor_comercial` | int | 0 % | Abertos entre 8h e 18h |
| `abertos_fora_hor_comercial` | int | 0 % | Complemento do anterior |
| `abertos_sem_ic` | int | 0 % | Sem item de configuração informado |
| `abertos_sem_classificacao` | int | 0 % | Sem `Produto`, `Categoria` e `Subcategoria` |
| `abertos_com_incidente_pai` | int | 0 % | Vinculados a um incidente-pai |

### Fechamentos (contados pela data de **encerramento**)

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `fechados` | int | 0 % | Incidentes encerrados no dia |
| `fechados_automatico` | int | 0 % | `Status = Encerrado Automaticamente`. Zero por construção na fatia `sem_intervencao` |
| `fechados_manual` | int | 0 % | `Status = Encerrado`. Idem |
| `fechados_kpi_violado` | int | 0 % | Encerrados com `KPI Violado? = SIM`. 0–5 |
| `fechados_entrou_kpi` | int | 0 % | Encerrados que entraram no cálculo de OLA |

> A grade vai da primeira à última data de **abertura**. Incidentes encerrados depois da última
> abertura ficam fora da contagem de fechamento — o notebook emite aviso de reconciliação quando
> isso ocorre.

### Duração e diversidade do dia

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `duracao_mediana_h` | float | 77,8 % | Mediana da duração dos incidentes **encerrados** no dia, em horas. Mediana e não média: a distribuição é dominada pela cauda |
| `duracao_p90_h` | float | 77,8 % | Percentil 90 da mesma distribuição |
| `ics_distintos` | int | 0 % | ICs distintos entre os abertos do dia |
| `times_distintos` | int | 0 % | Grupos designados distintos |
| `descricoes_distintas` | int | 0 % | Textos de descrição distintos |

O nulo alto das durações é esperado: a grade completa cria linhas para 1.095 dias, mas as duas
séries só passam a ter fechamento diário a partir de 2025.

### Derivadas

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `saldo_aberto_fechado` | int | 0 % | `abertos − fechados`. Negativo = a fila drenou |
| `taxa_monitoramento` | float | 71,9 % | `abertos_monitoramento / abertos × 100`. Nulo quando não houve abertura |
| `regime` | int | 0 % | 1, 2 ou 3 (ver convenções) |
| `backlog` | int | 0 % | Soma acumulada de `saldo_aberto_fechado` **dentro da série**. Pressão da fila |

### Concentração do evento

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `inc_por_ic` | float | 71,9 % | `abertos / ics_distintos`. Incidentes por item de configuração |
| `inc_por_descricao` | float | 71,9 % | `abertos / descricoes_distintas`. Repetição do mesmo texto no dia |
| `inc_por_time` | float | 71,9 % | `abertos / times_distintos`. Carga média por time acionado |

Separam o que a contagem bruta funde: 400 incidentes espalhados por 200 ICs é volume alto de
operação normal; 400 incidentes em 3 ICs é um incidente sistêmico. As duas situações têm o mesmo
`abertos`, e `ics_distintos` sozinho também não as distingue — só a razão.

Numerador e denominador já estavam ambos na tabela. Explicitar a divisão não acrescenta dado
nenhum: acrescenta uma **relação** que um modelo de árvore só aproximaria com muitos cortes, e
que por isso ele tende a não encontrar sozinho. Medido em `model_training.ipynb` §5.7, as três
juntas reduzem o MAE de teste em **4,8 %** — teste pareado em 30 sementes, `t = −5,4`, com ganho
em 26 delas. É o único ganho estatisticamente sólido de todo o estudo de features.

Nulas nos dias sem abertura, pelo mesmo motivo das demais razões: sem incidente, a razão é
indefinida, e zero diria "o dia foi totalmente concentrado".

### Janelas móveis e defasagens

Geradas por `adicionar_janelas()` dentro de cada série (`prioridade × tipo_tratamento`). Todas
as janelas são **fechadas em D, inclusive** — legítimo, porque o alvo está em D+1 ou D+7.

| Padrão | Colunas | Descrição |
|---|---|---|
| `abertos_soma_{7,14,30}d` · `abertos_media_{7,14,30}d` | 6 | Janelas móveis de aberturas |
| `abertos_lag_{1,2,3,7,14}` | 5 | Defasagens de `abertos`. Nulo nos primeiros k dias de cada série |
| `abertos_ac_mes` · `abertos_ac_ano` | 2 | Acumulados que zeram na virada do mês / do ano |
| `fechados_soma_{7,30}d` · `fechados_media_{7,30}d` | 4 | Janelas móveis de fechamentos |
| `fechados_lag_{1,7}` | 2 | Defasagens de `fechados` |
| `fechados_ac_mes` · `fechados_ac_ano` | 2 | Acumulados de fechamento |
| `kpi_violado_soma_30d` · `kpi_violado_media_30d` | 2 | Janela de 30 dias sobre `fechados_kpi_violado` |
| `kpi_violado_ac_mes` · `kpi_violado_ac_ano` | 2 | Acumulados de violação |

### Alvos

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `y_abertos_d1` | float | 0,1 % | `abertos` em D+1, dentro da mesma série (`shift(-1)`) |
| `y_abertos_d7` | float | 0,6 % | `abertos` **no** dia D+7 — previsão pontual |
| `y_abertos_acum_1a7` | float | 0,6 % | Soma de `abertos` em D+1…D+7 — previsão de volume agregado |

Os nulos são as últimas datas de cada série, onde o futuro não existe. **`d7` e `acum_1a7` são
duas leituras diferentes de "D+7"** e exigem modelos diferentes; a escolha é decisão de negócio
ainda em aberto.

> **Colunas que existiam na versão anterior e saíram:** `fechados_sem_intervencao` e
> `taxa_sem_intervencao` viraram a própria dimensão `tipo_tratamento`; `atingimento_ola_*`
> mudou para `s_fato_ola_prioridade`.

---

# s_fato_ola_prioridade.csv

**Grão:** `data × prioridade` · **Chave:** `data + prioridade` · **3.285 linhas × 9 colunas**.

O atingimento de OLA vive fora do fato principal porque as faixas foram calibradas sobre o
acumulado anual da **prioridade inteira**. Aplicá-las dentro do grão de `tipo_tratamento` daria
número sem significado de negócio: cada acumulado cairia para uma fatia e uma prioridade que
estourou a meta apareceria em 150 % só porque metade do volume foi para a outra linha.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` | date | 0 % | Chave |
| `prioridade` | int | 0 % | 2, 3, 4 |
| `fechados_prioridade` | int | 0 % | Fechamentos da prioridade inteira (soma das duas fatias de tipo) |
| `kpi_violado_prioridade` | int | 0 % | Violações da prioridade inteira |
| `fechados_prioridade_ac_ano` | int | 0 % | Acumulado anual de fechamentos |
| `kpi_violado_prioridade_ac_ano` | int | 0 % | Acumulado anual de violações |
| `atingimento_ola_duracao` | float | 33,3 % | % de atingimento pela regra de duração. Escala `[150, 125, 100, 75, 50, 0]` |
| `atingimento_ola_volume` | float | 33,3 % | % de atingimento pela regra de volume, mesma escala |
| `regime` | int | 0 % | 1, 2 ou 3 |

O sufixo `_prioridade` é deliberado: o fato principal já tem `fechados_ac_ano` e
`kpi_violado_ac_ano` no grão do tipo de tratamento, e os dois pares medem coisas diferentes.

**Os 33,3 % de nulo são P4 inteiro** — não há faixa de OLA definida para essa prioridade em
`FAIXAS_OLA_DURACAO` / `FAIXAS_OLA_VOLUME`. Confirmar com a área se P4 tem meta é um dos itens
pendentes do notebook.

---

# s_fato_diario_prioridade_turno.csv

**Grão:** `data × prioridade × tipo_tratamento × turno` · **26.280 linhas × 7 colunas**
(1.095 × 3 × 2 × 4).

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` | date | 0 % | Chave |
| `prioridade` | int | 0 % | 2, 3, 4 |
| `tipo_tratamento` | str | 0 % | `com_intervencao`, `sem_intervencao` |
| `turno` | str | 0 % | `madrugada` (0–6h) · `manha` (6–12h) · `tarde` (12–18h) · `noite` (18–24h) |
| `abertos` | int | 0 % | Abertos no turno, pela **hora de abertura** |
| `fechados` | int | 0 % | Fechados no turno, pela **hora de encerramento** |
| `regime` | int | 0 % | 1, 2 ou 3 |

`fechados` usa `turno_encerramento`, não o turno de abertura. Na versão anterior do notebook essa
coluna reaproveitava o turno de abertura e media "fechados hoje que tinham sido abertos de
madrugada" — que não é o que o nome promete.

A soma de `abertos` por `(data, prioridade, tipo_tratamento)` é assertada contra
`s_fato_diario_prioridade`.

---

# s_fato_diario.csv

**Grão:** `data` · **1.095 linhas × 43 colunas**.

O que **não** se divide por prioridade: contexto do dia inteiro, incluindo P1 e P5, mais as 22
colunas de calendário. Une-se ao fato por prioridade só na montagem da matriz do modelo.

### Volumes e contexto

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` | date | 0 % | Chave |
| `abertos_total` | int | 0 % | Todos os incidentes abertos no dia, **todas as prioridades**. 0–1.431 |
| `abertos_monitoramento_total` | int | 0 % | Subconjunto aberto por monitoramento |
| `abertos_p1` | int | 0 % | Prioridade 1 (1 registro em toda a base) |
| `abertos_p5` | int | 0 % | Prioridade 5 (333 registros) |
| `abertos_sem_ic_total` | int | 0 % | Sem item de configuração |
| `fechados_total` | int | 0 % | Encerrados no dia |
| `fechados_sem_intervencao_total` | int | 0 % | Encerrados com `Status = Sem Intervenção` |
| `ics_ativos_dia` | int | 0 % | ICs distintos com incidente no dia |
| `times_ativos_dia` | int | 0 % | Grupos designados distintos no dia |
| `incidentes_pai_distintos` | int | 0 % | Incidentes-pai distintos referenciados |
| `taxa_monitoramento_total` | float | 41,2 % | `abertos_monitoramento_total / abertos_total × 100` |
| `taxa_sem_intervencao_total` | float | 66,7 % | `fechados_sem_intervencao_total / fechados_total × 100` |

Os nulos altos das taxas são os dias de R1 sem movimento — divisão por zero vira nulo, não zero.

### Janelas

`abertos_total_soma_7d`, `abertos_total_media_7d`, `abertos_total_soma_30d`,
`abertos_total_media_30d`, `abertos_total_lag_1`, `abertos_total_lag_7`,
`abertos_total_ac_mes`, `abertos_total_ac_ano` — mesma semântica descrita no fato principal.

### Calendário

As 22 colunas de `s_dim_calendario` (menos `data`), unidas por `data`. Ver a seção da dimensão.

---

# s_fato_diario_time.csv

**Grão:** `data × time × tipo_tratamento` · **37.230 linhas × 8 colunas** (1.095 × 17 times × 2 tipos).

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` | date | 0 % | Chave |
| `time` | str | 0 % | Grupo designado, 17 valores (`Team01`…`Team17`) |
| `tipo_tratamento` | str | 0 % | Chave — `com_intervencao` ou `sem_intervencao` |
| `abertos` | int | 0 % | Incidentes do time no dia, **todas** as prioridades (inclusive P1 e P5) |
| `abertos_p2` / `abertos_p3` / `abertos_p4` | int | 0 % | Recorte por prioridade |
| `regime` | int | 0 % | 1, 2 ou 3 |

`Team14` concentra 75,7 % da base inteira.

**Por que `tipo_tratamento` está na chave.** Sem ele, uma feature de time seria o mesmo valor
replicado nas duas séries de cada prioridade, e o modelo não teria como distinguir um dia em que
o `Team14` dominou o que fechou sozinho de um dia em que ele dominou o que exigiu intervenção.

**Escopo de `abertos`.** Soma todas as prioridades de propósito: é o denominador de
`s_ft_concentracao`, e restringir a P2/P3/P4 deslocaria valores dessa tabela já consumidos a
jusante. Quem precisa fechar com `s_fato_diario_prioridade` usa
`abertos_p2 + abertos_p3 + abertos_p4` — conferido por assert no notebook.

---

# s_fato_diario_classe.csv

**Grão:** `data × classe_descricao × tipo_tratamento` · **24.090 linhas × 8 colunas**
(1.095 × 11 classes × 2 tipos).

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` | date | 0 % | Chave |
| `classe_descricao` | str | 0 % | Classe de negócio do alerta, ver domínio abaixo |
| `tipo_tratamento` | str | 0 % | Chave — `com_intervencao` ou `sem_intervencao` |
| `abertos` | int | 0 % | Abertos da classe no dia (**só P2, P3 e P4**) |
| `abertos_p2` / `abertos_p3` / `abertos_p4` | int | 0 % | Recorte por prioridade |
| `regime` | int | 0 % | 1, 2 ou 3 |

**Domínio de `classe_descricao`** — taxonomia fechada de 10 classes atribuída por LLM sobre os
templates que cobrem 95 % do volume, mais o rótulo de cauda:
`disponibilidade_servico`, `performance_degradada`, `erro_aplicacao`, `infraestrutura_rede`,
`armazenamento_disco`, `banco_de_dados`, `certificado_seguranca`, `backup_replicacao`,
`job_processamento`, `outros`, `nao_rotulado`.

`nao_rotulado` são os templates fora do escopo de 95 % — cauda longa, não falha de rotulagem.

As features derivadas desta tabela (`classes_ativas`, `entropia_classes`, `hhi_classes`,
`share_classe_lider`) vivem em [`s_ft_classe`](#s_ft_classecsv); a versão no grão dia continua
entrando em `s_tabela_modelo`.

**Reprodutibilidade da rotulagem.** A classe vem de um LLM, que não é determinístico: reexecutar
a rotulagem devolveria classes diferentes para parte dos templates e deslocaria em silêncio todas
as features derivadas. Por isso o notebook lê o mapa `template_descricao → classe` já gravado em
`s_dim_template.csv` e só chama a API para templates que ainda não estejam lá.

---

# s_ft_ic.csv

**Grão:** `data` · **1.095 linhas × 14 colunas**.

Features de item de configuração no grão do dia, prontas para o modelo.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` | date | 0 % | Chave |
| `ics_na_base` | int | 0 % | ICs já vistos até o dia (o painel de um IC começa na sua primeira ocorrência). 1–9.172 |
| `ics_ativos` | int | 0 % | ICs com pelo menos um incidente nos 50 dias anteriores |
| `ics_outliers` | int | 0 % | ICs cujo volume na janela ultrapassa Q3 + 1,5·IQR, calculado **só entre os ativos** |
| `ics_inativos` | int | 0 % | ICs sem incidente há mais de 30 dias |
| `volume_janela_outliers` | float | 0 % | Soma do volume da janela dos ICs outlier |
| `pct_ics_outliers` | float | 0,1 % | `ics_outliers / ics_ativos × 100`. Nulo quando não há IC ativo |
| `ics_novos` | int | 0 % | ICs que aparecem pela primeira vez no dia |
| `ics_novos_soma_7d` · `_media_7d` · `_soma_30d` · `_media_30d` · `_lag_1` · `_lag_7` | float | 0–0,6 % | Janelas e defasagens de `ics_novos` |

O corte de outlier é recalculado **por dia** e apenas sobre os ICs ativos. Sem esse filtro, a
massa de ICs zerados puxaria os quartis para zero e quase tudo viraria outlier.

---

# s_ft_concentracao.csv

**Grão:** `data` · **1.095 linhas × 4 colunas**.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` | date | 0 % | Chave |
| `hhi_times` | float | 0 % | Índice Herfindahl-Hirschman sobre as participações diárias dos times. 1 = um time absorve tudo; ~1/n = carga uniforme. Dia sem incidente = 0 |
| `times_com_incidente` | int | 0 % | Times com pelo menos um incidente no dia. 0–15 |
| `share_time_lider` | float | 0 % | Participação do time mais carregado do dia, 0–1 |

Serve para detectar dias em que o roteamento saiu do padrão. Se o alvo depende de roteamento,
isso é sinal, não ruído.

---

# s_ft_concentracao_tipo.csv

**Grão:** `data × tipo_tratamento` · **2.190 linhas × 5 colunas**.

As mesmas três medidas de `s_ft_concentracao`, calculadas dentro de cada série em vez de sobre o
dia inteiro. Colunas idênticas às da irmã, mais `tipo_tratamento` na chave.

O HHI é sempre calculado sobre a distribuição entre os **17 times**: a tabela de origem chega no
grão `data × time × tipo_tratamento` e é reagregada antes da conta. Sem esse passo o índice
mediria a dispersão entre células time × tipo, que é outro número com o mesmo nome — o tipo de
erro que não levanta exceção nenhuma.

---

# s_ft_classe.csv

**Grão:** `data × tipo_tratamento` · **2.190 linhas × 6 colunas**.

Espelho de `s_ft_concentracao_tipo` para as classes de alerta. A diversidade cai quando um único
tipo de alerta domina o dia, que costuma ser a assinatura de um incidente sistêmico.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` | date | 0 % | Chave |
| `tipo_tratamento` | str | 0 % | Chave |
| `classes_ativas` | int | 0 % | Classes com pelo menos um incidente. 0–11 |
| `entropia_classes` | float | 0 % | Shannon normalizada (0–1) da distribuição de classes do dia |
| `hhi_classes` | float | 0 % | Herfindahl-Hirschman sobre as participações das classes |
| `share_classe_lider` | float | 0 % | Participação da classe mais volumosa, 0–1 |

---

# s_ft_texto.csv

**Grão:** `data × prioridade × tipo_tratamento` · **6.570 linhas × 14 colunas**.

*Frequency encoding* de `Descrição Resumida` (via template) e de `Grupo designado`. Responde uma
pergunta que nenhuma outra feature da camada faz: **os incidentes de hoje são do tipo de sempre,
ou é texto raro/inédito?** Dois dias com o mesmo `abertos` — um dominado por alertas repetidos,
outro cheio de descrição nova — significam coisas opostas para a operação.

O encoding é por frequência, e não one-hot, por cardinalidade: são 13.317 templates distintos.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` / `prioridade` / `tipo_tratamento` | — | 0 % | Chave |
| `incidentes` | int | 0 % | Incidentes na célula. Zero real quando não houve nenhum |
| `freq_template_media` | float | ~72 % | Média, sobre os incidentes do dia, da frequência expansiva do template |
| `freq_template_mediana` | float | ~72 % | Idem, mediana |
| `freq_template_p10` | float | ~72 % | Idem, percentil 10 — lê a cauda rara do dia |
| `pct_template_novo` | float | ~72 % | % dos incidentes cujo template nunca apareceu antes de D |
| `templates_novos` | int | 0 % | Templates distintos inéditos no dia |
| `freq_time_media` | float | ~72 % | Mesma lógica para o grupo designado |
| `freq_time_min` | float | ~72 % | Frequência do time mais raro do dia |
| `entropia_templates_dia` | float | ~72 % | Shannon normalizada da distribuição de templates |
| `entropia_times_dia` | float | ~72 % | Shannon normalizada da distribuição de times |
| `regime` | int | 0 % | 1, 2 ou 3 |

### A frequência é expansiva, não global

A frequência de um valor é sempre `n(valor em dias < D) / n(total em dias < D)` — contada
**apenas sobre o passado**. A frequência global embutiria o futuro: um template que só nasce em
outubro teria frequência alta em janeiro. É um vazamento que não aparece em validação nenhuma,
porque a coluna continua preenchida e plausível.

Sendo causal por construção, a tabela vale para **qualquer** corte de treino/teste — a camada
silver não precisa conhecer as janelas definidas em `model_training.ipynb`, e um corte novo lá
não obriga a regravar nada aqui.

### Sobre os ~72 % de nulos

São células sem incidente nenhum, quase todas em R1 (92,1 % das células de R1 são vazias, contra
47,2 % em R2 e **0,7 % em R3**). Média de frequência e entropia de um dia vazio são indefinidas:
preenchê-las com zero diria "os textos de hoje são raríssimos" e "o dia foi totalmente
concentrado", que é o oposto do que um dia vazio significa. Ficam nulas — `incidentes == 0`
distingue os dois casos, e o XGBoost trata nulo nativamente. Na janela efetivamente modelada
(R3) o preenchimento é praticamente total.

---

# s_dim_calendario.csv

**Grão:** `data` · **1.460 linhas × 23 colunas**.

### A única tabela que vai além do fim dos dados

Os dados terminam em 2025-12-31; esta tabela vai até **2026-12-31**, um ano à frente. São duas
razões, e as duas são operacionais:

1. **Prever D+1 exige o calendário do dia-alvo**, que por definição ainda não tem incidente.
   SARIMA (exógenas de feriado), Prophet (regressores) e LSTM (as 11 features) todos dependem
   disso. Com o calendário terminando junto com os dados, nenhum deles conseguiria prever o
   próximo dia — é o que `exportar_modelos.py` e o serviço em `models/` consomem.
2. **`vespera_feriado` é `feriado.shift(-1)`**, então no último dia da tabela ele vira 0 por
   falta de dia seguinte. Sem a folga, 2025-12-31 aparecia como não-véspera — sendo que
   2026-01-01 é Ano Novo. A extensão corrige esse valor, que cai dentro da janela de teste.

O calendário é determinístico, então estender não é extrapolação: é só calcular. Todas as demais
tabelas continuam limitadas ao período com dado, porque os merges de calendário têm sempre o fato
à esquerda (`fato.merge(calendario, how="left")`) e as linhas futuras não vazam.

O horizonte é `HORIZONTE_CALENDARIO` em `data_exploration.ipynb` §2.3.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `data` | date | 0 % | Chave, 2023-01-02 a **2026-12-31** |
| `nome_feriado` | str | 95,7 % | Nome do feriado, 16 distintos |
| `escopo_feriado` | str | 95,7 % | `BR` nacional · `SP` municipal de São Paulo |
| `feriado` | int | 0 % | 0/1 |
| `dia_semana` | int | 0 % | 0 = segunda … 6 = domingo |
| `nome_dia_semana` | str | 0 % | `Seg`…`Dom` |
| `fim_de_semana` | int | 0 % | 0/1 (sábado ou domingo) |
| `dia_util` | int | 0 % | 0/1 (dia de semana e não feriado) |
| `tipo_dia` | str | 0 % | `dia_util` · `fnds_feriado` |
| `dia_mes` | int | 0 % | 1–31 |
| `mes` | int | 0 % | 1–12 |
| `trimestre` | int | 0 % | 1–4 |
| `ano` | int | 0 % | 2023–2025 |
| `ano_mes` | str | 0 % | `YYYY-MM`, 36 valores |
| `num_dia_util` | int | 0 % | Enésimo dia útil do mês, 0–23. Em dia não útil repete o último dia útil anterior (`ffill`), não 0 — 0 sugeriria "início do mês" ao modelo |
| `vespera_feriado` | int | 0 % | 0/1, o dia seguinte é feriado |
| `pos_feriado` | int | 0 % | 0/1, o dia anterior foi feriado |
| `dia_ano` | int | 0 % | 1–366 |
| `sen_ano` / `cos_ano` | float | 0 % | Codificação cíclica anual — 31/12 e 01/01 ficam próximos |
| `sen_semana` / `cos_semana` | float | 0 % | Codificação cíclica semanal |
| `regime` | int | 0 % | 1, 2 ou 3 |

Os feriados são os nacionais (incluindo Carnaval, Cinzas e Corpus Christi) mais **25/01 e 09/07,
municipais de São Paulo**. Se a operação for nacional, filtre por `escopo_feriado != 'SP'` ou
desligue `INCLUIR_FERIADOS_SP` no notebook.

---

# s_dim_ic.csv

**Grão:** `ic` · **9.171 linhas × 18 colunas**. Exclui os incidentes sem IC informado.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `ic` | str | 0 % | Chave, `IC00001`… |
| `incidentes_total` | int | 0 % | Incidentes no período inteiro. 1–6.069, mediana 2 |
| `primeira_data` / `ultima_data` | date | 0 % | Primeira e última abertura |
| `dias_ativos` | int | 0 % | Dias distintos com incidente |
| `duracao_mediana_h` | float | 0 % | Mediana de `duracao_horas` |
| `times_distintos` | int | 0 % | Grupos designados que atenderam o IC. 1–10 |
| `categorias_distintas` | int | 0 % | Categorias distintas. 0 quando o IC nunca é classificado |
| `ciclo_vida_dias` | int | 0 % | `ultima_data − primeira_data` |
| `dias_desde_ultimo` | int | 0 % | Dias entre a última ocorrência e 31/12/2025 |
| `inativo` | int | 0 % | 0/1, `dias_desde_ultimo > 30` |
| `intensidade` | float | 0 % | `incidentes_total / dias_ativos` |
| `assinatura_monitoramento` | str | 0 % | 3 caracteres, um por regime: `-` ausente · `M` monitorado (≥ 75 % das aberturas) · `H` majoritariamente manual. Ex.: `-HM` = não existia em R1, manual em R2, monitorado em R3 |
| `jornada_monitoramento` | str | 0 % | Tradução da assinatura: `Monitorado nativo novo` · `Monitorado nativo antigo` · `Migrado no R2` · `Migrado no R3` · `Sempre manual` · `Oscilante (termina monitorado)` · `Regrediu para manual` |
| `grav_r2` | float | 42,4 % | Índice de gravidade em R2 (ver `s_dim_ic_regime`). Nulo = IC ausente no regime |
| `grav_r3` | float | 32,7 % | Idem em R3 |
| `delta_grav_r3_r2` | float | 74,0 % | `grav_r3 − grav_r2`. Nulo quando o IC não existe nos dois regimes |
| `perfil_evolucao` | str | 0 % | `Agravou em R3` (delta > 15) · `Aliviou em R3` (delta < −15) · `Estável` · `Sem comparação` |

Em R3, 16 % dos ICs ativos concentram 89 % dos incidentes. Features de IC devem ser construídas
sobre a cauda pesada, não sobre médias da base toda.

---

# s_dim_ic_regime.csv

**Grão:** `ic × regime` · **Chave:** `ic + regime` · **11.805 linhas × 20 colunas**.

Formato longo — um IC aparece em 1, 2 ou 3 linhas, conforme os regimes em que teve atividade.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `ic` / `regime` | str / int | 0 % | Chave |
| `incidentes` | int | 0 % | Incidentes do IC no regime |
| `dias_ativos` | int | 0 % | Dias distintos com incidente |
| `primeira_data` / `ultima_data` | date | 0 % | Extremos dentro do regime |
| `duracao_mediana_h` | float | 0 % | Mediana da duração |
| `monitorados` | int | 0 % | Aberturas por monitoramento |
| `sem_intervencao` | int | 0 % | Incidentes com `Status = Sem Intervenção` |
| `categorias_distintas` / `produtos_distintos` / `times_distintos` | int | 0 % | Diversidade |
| `inc_p1` … `inc_p5` | int | 0 % | Mix de prioridades |
| `pct_monitorado` | float | 0 % | `monitorados / incidentes × 100` |
| `media_inc_por_dia_ativo` | float | 0 % | `incidentes / dias_ativos` |
| `indice_gravidade` | float | 0,3 % | Média ponderada da prioridade reescalada para **100–300**: 300 = tudo P2, 200 = tudo P3, 100 = tudo P4. Ignora P1 e P5. Nulo quando o IC só teve P1/P5 no regime |

---

# s_dim_time_regime.csv

**Grão:** `time × regime` · **Chave:** `time + regime` · **48 linhas × 25 colunas**
(17 times, nem todos presentes nos 3 regimes).

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `time` / `regime` | str / int | 0 % | Chave |
| `incidentes` | int | 0 % | Volume do time no regime. Máximo 79.871 (Team14 em R3) |
| `dias_ativos` | int | 0 % | Dias distintos com incidente |
| `primeira_data` / `ultima_data` | date | 0 % | Extremos dentro do regime |
| `duracao_mediana_h` | float | 0 % | Mediana da duração |
| `pct_monitorado` | float | 0 % | % de aberturas por monitoramento |
| `pct_sem_intervencao` | float | 0 % | % de incidentes com `Status = Sem Intervenção` |
| `ics_distintos` | int | 0 % | ICs atendidos |
| `entropia_categoria` | float | 0 % | Entropia de Shannon normalizada (0–1) sobre a distribuição de categorias. 0 = o time só atende uma; 1 = atende todas por igual |
| `entropia_produto` / `entropia_ic` / `entropia_hora` | float | 0 % | Idem para produto, IC e hora de abertura |
| `horas_cobertas` | int | 0 % | Horas do dia distintas com atividade. 24 = plantão contínuo |
| `inc_p1` … `inc_p5` | int | 0 % | Mix de prioridades |
| `pct_p2` / `pct_p3` / `pct_p4` | float | 0 % | Mix em percentual |
| `share_regime` | float | 0 % | % do volume do regime que passou pelo time |
| `media_inc_por_dia_ativo` | float | 0 % | `incidentes / dias_ativos` |

A entropia normalizada existe porque `nunique` cresce com o volume: um time com 90 mil incidentes
toca mais categorias que um com 300 independentemente de ser mais generalista. A entropia é
comparável entre times de portes diferentes.

---

# s_dim_template.csv

**Grão:** `template_descricao` · **13.317 linhas × 22 colunas**.

`Descrição Resumida` tem 17.787 valores distintos, majoritariamente gerados por template de
alerta. A normalização (mascaramento de IP, host, ID, número, data, caminho, URL) colapsa esses
textos em 13.317 templates — é sobre eles que rodam o agrupamento e a rotulagem, e é isso que
torna a etapa de LLM viável: o custo é proporcional a templates, não a incidentes.

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `template_descricao` | str | 0 % | Chave. Texto normalizado, com marcadores `<IP>`, `<HOST>`, `<NUM>`, `<NOME_NUM>`, `<DATA>`, `<MEDIDA>`, `<PATH>`, `<URL>`, `<UUID>`, `<INC>`, `<HEX>`, `<HASH>`, `<EMAIL>`, `<HORA>` |
| `incidentes` | int | 0 % | Volume do template. 1–28.728 |
| `exemplo` | str | 0 % | Uma `Descrição Resumida` original que gerou o template |
| `pct_monitorado` | float | 0 % | % aberto por monitoramento |
| `pct_sem_intervencao` | float | 0 % | % com `Status = Sem Intervenção` |
| `duracao_mediana_h` | float | 0 % | Mediana da duração |
| `times_distintos` | int | 0 % | Times que receberam o template |
| `time_principal` | str | 0 % | Time com mais ocorrências (moda) |
| `ics_distintos` | int | 0 % | ICs que dispararam o template. 1–2.921 |
| `primeira_data` / `ultima_data` | date | 0 % | Extremos de ocorrência |
| `pct_volume` | float | 0 % | % do volume total da base |
| `pct_acumulado` | float | 0 % | Acumulado de `pct_volume`, em ordem decrescente de volume |
| `no_escopo` | int | 0 % | 0/1 — o template está entre os que somam 95 % do volume. Só esses foram agrupados e rotulados |
| `inc_p1` … `inc_p5` | int | 0 % | Mix de prioridades |
| `prioridade_dominante` | int | 0 % | Prioridade com mais ocorrências no template |
| `cluster` | int | 0 % | Grupo do KMeans sobre TF-IDF de n-gramas de caractere (3–5), ponderado por volume. **`-1` = fora do escopo de 95 %** |
| `classe` | str | 0 % | Classe de negócio atribuída por LLM na taxonomia fechada de 10 valores. Templates fora do escopo ficam `nao_rotulado` |

O template mais frequente — `problem: check application monitoring` — sozinho responde por 23,4 %
da base.

---

# s_tabela_modelo.csv

**Grão:** `data`, formato **largo** · **365 linhas × 392 colunas**.

Matriz pronta para o estimador. É a única tabela em formato largo do projeto e a única restrita
aos **regimes modeláveis (R2 e R3)** — daí as 365 linhas, de 2025-01-01 a 2025-12-31, em vez de
1.095.

Une três grãos:

```
data × prioridade × tipo_tratamento   (s_fato_diario_prioridade)   -> p{prio}_{tipo}_{métrica}
data × prioridade                     (s_fato_ola_prioridade)      -> p{prio}_{métrica}
data                                  (s_fato_diario, s_ft_ic,
                                       s_ft_concentracao, ft_classe) -> nome original
```

A montagem tem guarda ativa contra colisão de nomes entre grãos: coluna repetida levanta erro em
vez de virar `_x`/`_y` silenciosamente.

### Bloco 1 — as 6 séries: `p{2,3,4}_{com,sem}_intervencao_{métrica}`

**312 colunas** = 52 métricas × 6 séries. As métricas são exatamente as colunas de
`s_fato_diario_prioridade` fora da chave e de `regime`:

`abertos` · `abertos_monitoramento` · `abertos_manual` · `abertos_hor_comercial` ·
`abertos_fora_hor_comercial` · `abertos_sem_ic` · `abertos_sem_classificacao` ·
`abertos_com_incidente_pai` · `fechados` · `fechados_automatico` · `fechados_manual` ·
`fechados_kpi_violado` · `fechados_entrou_kpi` · `duracao_mediana_h` · `duracao_p90_h` ·
`ics_distintos` · `times_distintos` · `descricoes_distintas` · `saldo_aberto_fechado` ·
`taxa_monitoramento` · `backlog` · as 13 janelas/lags/acumulados de `abertos` · as 8 de
`fechados` · as 4 de `kpi_violado` · `y_abertos_d1` · `y_abertos_d7` · `y_abertos_acum_1a7`.

Exemplos: `p3_com_intervencao_y_abertos_d1`, `p4_sem_intervencao_abertos_media_7d`.

**Os 6 alvos** para D+1 são as colunas `p{prio}_{tipo}_y_abertos_d1`; para D+7,
`…_y_abertos_d7` (contagem no dia) ou `…_y_abertos_acum_1a7` (soma da semana).

Colunas degeneradas por construção, esperadas e não bugs: as `sem_intervencao_fechados_automatico`,
`…_fechados_manual`, `…_fechados_kpi_violado`, `…_fechados_entrou_kpi` e todas as
`…_kpi_violado_*` são **zero em toda a série** — os status e as regras de KPI que as alimentam
pertencem ao lado `com_intervencao`.

### Bloco 2 — grão prioridade: `p{2,3,4}_{métrica}`

**18 colunas**, de `s_fato_ola_prioridade` (sem `regime`): `fechados_prioridade`,
`kpi_violado_prioridade`, `fechados_prioridade_ac_ano`, `kpi_violado_prioridade_ac_ano`,
`atingimento_ola_duracao`, `atingimento_ola_volume`.

Pivotadas à parte para não repetir o mesmo valor de OLA nas duas fatias de tipo.
`p4_atingimento_ola_duracao` e `p4_atingimento_ola_volume` são **100 % nulas** — P4 não tem faixa
de OLA definida.

### Bloco 3 — grão dia: nome original

**61 colunas**, sem prefixo:

| Origem | Colunas |
|---|---|
| `s_fato_diario` | 41 colunas (volumes totais, taxas, calendário, janelas de `abertos_total`), menos `data` e `regime` |
| `s_ft_ic` | 13 colunas de item de configuração |
| `s_ft_concentracao` | `hhi_times`, `times_com_incidente`, `share_time_lider` |
| `s_ft_classe` (grão dia) | `classes_ativas`, `entropia_classes`, `hhi_classes`, `share_classe_lider` — quão distribuído está o volume entre as classes de alerta; cai quando um único tipo domina, padrão típico de incidente sistêmico |

### Nulos

Praticamente ausentes no recorte 2025, com três exceções conhecidas:

| Colunas | Nulo | Motivo |
|---|---|---|
| `…_y_abertos_d1` | 0,3 % | Último dia da série |
| `…_y_abertos_d7` · `…_y_abertos_acum_1a7` | 1,9 % | Últimos 7 dias |
| `…_sem_intervencao_duracao_mediana_h` · `_duracao_p90_h` · `_taxa_monitoramento` | 57–67 % | Não houve fechamento (ou abertura) daquela série no dia — em R2 essas séries mal existem |
| `p4_atingimento_ola_*` | 100 % | P4 sem faixa de OLA |

---

## Reprodução

Todas as tabelas são regeradas executando `notebooks/data_exploration.ipynb` do início ao fim.
A escrita está concentrada em um único bloco na Seção 4, e o `CATALOGO` daquela seção é a fonte
canônica de grão e chave — tabela nova precisa de entrada no catálogo antes de `salvar()` aceitar
gravá-la.
