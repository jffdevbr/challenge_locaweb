# Dicionário do dashboard — `Dashboard_Challenge_Locaweb.pbix`

Documenta as 6 páginas do relatório: para que cada uma serve, o que tem em cada uma e
**como cada número é calculado** — o DAX literal de cada medida e o campo de cada eixo.

Companheiro dos dicionários de dado das camadas: aqui não se descreve o dado, descreve-se
**o que o relatório faz com ele**.

| Item | Valor |
|---|---|
| Arquivo | `Dashboard_Challenge_Locaweb.pbix` |
| Formato do relatório | PBIR (`Report/definition/pages/…`, um JSON por visual) |
| Tabela de medidas | `_Medidas` — tabela calculada `ROW("Coluna1", BLANK())`, sem dado próprio |
| Medidas no modelo | 70 (56 referenciadas em visuais, 14 intermediárias ou ociosas) |
| Canvas | 1920 × 1080, `FitToPage` |
| Tema | `Tema_Incidentes_FIAP.json` sobre o base `Fluent2-CY26SU08` |

---

## Índice

1. [Modelo semântico](#1-modelo-semântico)
2. [Convenções das 6 páginas](#2-convenções-das-6-páginas)
3. [Página 1 — Visão geral](#3-página-1--visão-geral)
4. [Página 2 — Classificação](#4-página-2--classificação)
5. [Página 3 — Times](#5-página-3--times)
6. [Página 4 — ICs](#6-página-4--ics)
7. [Página 5 — Ruído](#7-página-5--ruído)
8. [Página 6 — OLA](#8-página-6--ola)
9. [Apêndice A — medidas de cor](#9-apêndice-a--medidas-de-cor)
10. [Apêndice B — medidas sem uso atual](#10-apêndice-b--medidas-sem-uso-atual)
11. [Apêndice C — ressalvas conhecidas](#11-apêndice-c--ressalvas-conhecidas)

---

## 1. Modelo semântico

15 tabelas carregadas em modo *Import*.

### Fatos

| Tabela | Grão | Usada em |
|---|---|---|
| `s_fato_diario_prioridade` | `data × prioridade × tipo_tratamento` | Visão geral, Classificação, Ruído, backlog do OLA |
| `s_fato_diario_classe` | `data × classe_descricao × tipo_tratamento` | Classificação, Ruído |
| `s_fato_diario_time` | `data × time × tipo_tratamento` | Times |
| `s_fato_ola_prioridade` | `data × prioridade` | OLA |

### Dimensões

| Tabela | Chave | Papel no relatório |
|---|---|---|
| `s_dim_calendario` | `data` | eixo de tempo de **todos** os gráficos temporais; fonte do filtro de data |
| `dim_prioridade` | `prioridade` | fonte do filtro P2/P3/P4 (`Prioridade_Rotulo`) |
| `dim_time` | `time` | eixo da página Times; guarda `pct_p2/p3/p4` |
| `dim_classe` | `classe_descricao` | eixo dos gráficos de classe |
| `s_dim_ic` | `ic` | tudo da página ICs |
| `s_dim_template` | `template_descricao` | Top 10 templates e Template Líder |
| `s_dim_ic_regime`, `s_dim_time_regime` | — | carregadas, **não usadas em nenhum visual** |
| `part-00000…`, `part-00001…` | — | partições brutas da bronze, não usadas em visuais |

### A diferença de escopo que mais confunde

Duas tabelas contam incidentes com escopos diferentes. **Isso explica qualquer divergência
entre páginas:**

| Coluna | Escopo | Total |
|---|---|---|
| `s_fato_diario_prioridade[abertos]` | **só P2, P3 e P4** | 122.209 |
| `s_fato_diario_time[abertos]` | todas as prioridades, inclusive P1 e P5 | 122.543 |

A medida `Incidentes por Time` foi construída sobre `abertos_p2 + abertos_p3 + abertos_p4`
justamente para fechar com `Total Incidentes`. A diferença de 334 registros é P1 (1) + P5 (333).

---

## 2. Convenções das 6 páginas

Todas as páginas repetem a mesma moldura:

| Elemento | Posição | O que é |
|---|---|---|
| Barra lateral | `0,0` · 280×1080 | forma retangular preenchida com `#01386A`, a cor da logo |
| Logo Ddip | `55,45` · 170×170 | imagem `logo_ddip.png` do pacote de recursos |
| Texto "Ddip" | `20,230` · 240×70 | caixa de texto, 28pt, `#F2E8DC` |
| Navegador de página | `20,320` · 240×340 | visual `pageNavigator`, gera um botão por página automaticamente |
| Filtro de prioridade | `≈15,667` · 249×101 | segmentação em `dim_prioridade[Prioridade_Rotulo]`, **sincronizada entre as 6 páginas** (`syncGroup: Prioridade_Rotulo`) |
| Filtro de data | `1470,14` · 420×90 | segmentação em `s_dim_calendario[data]`, tipo intervalo. **Não é sincronizada** — cada página tem a sua |
| Título da página | `310,24` · 1000×70 | caixa de texto |

**Estado do navegador.** No Power BI Desktop, em modo de edição, botões e navegadores de
página exigem **Ctrl + clique**. Clique simples apenas seleciona o objeto. Publicado no
Power BI Service o clique simples funciona.

**Estilo do navegador.** Fundo transparente no estado padrão, texto branco 14pt; estado
`selected` com fundo `#F2E8DC` e texto `#01386A` em negrito; `hover` com fundo branco a 78%
de transparência.

---

## 3. Página 1 — Visão geral

**Para que serve.** Estabelecer o tamanho e o formato do problema em quatro números, e mostrar
as duas séries alvo (com e sem intervenção) se separando no tempo.

### Cartões

| Cartão | Medida | DAX |
|---|---|---|
| Total Incidentes | `Total Incidentes` | `SUM(s_fato_diario_prioridade[abertos])` |
| % Ruído do Total | `% Ruído do Total` | `DIVIDE([Incidentes Sem Intervenção], [Total Incidentes])` |
| % Team14 | `% Team14` | `CALCULATE([Share do Time], dim_time[time] = "Team14")` |
| Template Líder % | `Template Líder %` | `MAX(s_dim_template[pct_volume])` |

Medidas encadeadas por trás desses quatro:

```dax
Incidentes Sem Intervenção =
CALCULATE([Total Incidentes], s_fato_diario_prioridade[tipo_tratamento] = "sem_intervencao")

Share do Time =
DIVIDE([Incidentes por Time], CALCULATE([Incidentes por Time], ALL(dim_time)))

Template Líder (nome) =
MAXX(TOPN(1, s_dim_template, s_dim_template[pct_volume], DESC), s_dim_template[template_descricao])
```

O cartão de Template Líder usa `Template Líder (nome)` como rótulo de referência — é o texto
`problem: check application monitoring` que aparece embaixo do 23,4%.

### Sparklines

Três mini-gráficos de área de 195×80 sobrepostos aos cartões, todos com **eixo
`s_dim_calendario[ano_mes]`** e, no eixo Y, a mesma medida do cartão que acompanham:
`Total Incidentes`, `% Ruído do Total` e `% Team14`.

### Gráfico principal — Evolução mensal dos incidentes

| Papel | Campo |
|---|---|
| Eixo | `s_dim_calendario[ano_mes]` |
| Legenda (séries) | `s_fato_diario_prioridade[tipo_tratamento]` |
| Valores | `Total Incidentes` |

Duas linhas, uma por valor de `tipo_tratamento` (`com_intervencao` e `sem_intervencao`).
É a única visualização do relatório que quebra pela dimensão de tratamento no eixo de séries.

---

## 4. Página 2 — Classificação

**Para que serve.** Mostrar que a classificação oficial do ITSM não sustenta análise, e que a
classificação construída pelo projeto — template + LLM — sustenta.

### Cartões

```dax
% Cauda Não Rotulada =
DIVIDE(
    CALCULATE([Incidentes por Classe], s_fato_diario_classe[classe_descricao] = "nao_rotulado"),
    [Incidentes por Classe]
)

Classificação Oficial Vazia =
DIVIDE(
    SUM(s_fato_diario_prioridade[abertos_sem_classificacao]),
    SUM(s_fato_diario_prioridade[abertos])
)
```

`abertos_sem_classificacao` marca os incidentes em que `Produto`, `Categoria` **e**
`Subcategoria` vieram nulos — os três ao mesmo tempo.

> **Quebra por regime.** O agregado de ~64% esconde o principal. Calculado sobre a silver:
> R1 **0,0%** · R2 **3,5%** · R3 **82,1%**. A classificação oficial não é ruim há três anos —
> ela colapsou no regime 3, que é o período modelado.

### Gráfico — Incidentes por Classe

| Papel | Campo |
|---|---|
| Eixo | `dim_classe[classe_descricao]` |
| Valores | `Incidentes por Classe` |
| Cor das barras | `Cor Classe (verde)` |

A medida de volume respeita o filtro de prioridade trocando de coluna de origem:

```dax
Incidentes por Classe =
IF(
    ISFILTERED(dim_prioridade[prioridade]),
    SUMX(
        VALUES(dim_prioridade[prioridade]),
        SWITCH(dim_prioridade[prioridade],
            2, SUM(s_fato_diario_classe[abertos_p2]),
            3, SUM(s_fato_diario_classe[abertos_p3]),
            4, SUM(s_fato_diario_classe[abertos_p4])
        )
    ),
    SUM(s_fato_diario_classe[abertos])
)
```

Sem filtro de prioridade ela soma `abertos`; com filtro, soma só as colunas das prioridades
selecionadas. É o padrão que se repete em várias medidas do relatório.

### Tabela — templates por participação

Colunas diretas de `s_dim_template`, sem medida: `template_descricao` e
`Soma de pct_volume`. Ordenada por participação decrescente.

---

## 5. Página 3 — Times

**Para que serve.** Mostrar que a carga não está distribuída e — com o filtro de tratamento —
que a parte concentrada é ruído automático, não trabalho.

### Cartões e medidor

```dax
Incidentes por Time =
  SUM(s_fato_diario_time[abertos_p2])
+ SUM(s_fato_diario_time[abertos_p3])
+ SUM(s_fato_diario_time[abertos_p4])

Share do Time =
DIVIDE([Incidentes por Time], CALCULATE([Incidentes por Time], ALL(dim_time)))

% Team14 = CALCULATE([Share do Time], dim_time[time] = "Team14")

Índice de Concentração (HHI) =
SUMX(
    VALUES(dim_time[time]),
    DIVIDE([Incidentes por Time], CALCULATE([Incidentes por Time], ALL(dim_time))) ^ 2
)
```

**O HHI é literalmente a soma dos quadrados das fatias de cada time.** O medidor tem eixo
fixo de 0 a 1: perto de 0 é carga dividida por igual, 1 é um time absorvendo tudo. Com 17
times, distribuição uniforme daria 1/17 = 0,059.

Verificação de sanidade: o Team14 tem 75,7% do volume, e 0,757² = 0,573 — praticamente todo
o índice de 0,59 é um time só.

### Gráfico — Incidentes por time e prioridade

| Papel | Campo |
|---|---|
| Eixo | `dim_time[time]` |
| Valores | `Incidentes P2 (time)`, `Incidentes P3 (time)`, `Incidentes P4 (time)` |

```dax
Incidentes P2 (time) = IF(2 IN VALUES(dim_prioridade[prioridade]), SUM(s_fato_diario_time[abertos_p2]))
Incidentes P3 (time) = IF(3 IN VALUES(dim_prioridade[prioridade]), SUM(s_fato_diario_time[abertos_p3]))
Incidentes P4 (time) = IF(4 IN VALUES(dim_prioridade[prioridade]), SUM(s_fato_diario_time[abertos_p4]))
```

O `IF(n IN VALUES(...))` faz a série sumir da legenda quando a prioridade é desmarcada no
filtro — em vez de virar uma linha de zeros.

### Filtro — Com × sem intervenção

Segmentação em **`s_fato_diario_time[tipo_tratamento]`**, não em
`s_fato_diario_prioridade`. A escolha da tabela é obrigatória: as medidas desta página leem
`s_fato_diario_time`, e um fato não filtra outro fato. Uma segmentação na tabela errada
apareceria na tela sem filtrar nada.

Efeito medido ao selecionar `sem_intervencao`:

| Indicador | Base inteira | Só sem intervenção |
|---|---|---|
| % Team14 | 75,7% | 94,0% |
| HHI | 0,59 | 0,88 |
| Incidentes por Time | 122 Mil | 80 Mil |

### Matriz — mix de prioridade por time

Linhas `dim_time[time]`, valores `Soma de pct_p2`, `pct_p3`, `pct_p4`. São colunas da
dimensão, pré-calculadas na silver — **não respondem ao filtro de data nem ao de tratamento**,
porque são atributos do time, não agregações de fato.

---

## 6. Página 4 — ICs

**Para que serve.** Localizar de onde vem o volume (poucos equipamentos) e mostrar que volume
e gravidade apontam para lados opostos.

### Os quatro cartões

```dax
ICs Críticos (top 16%) =
VAR Corte = PERCENTILE.INC(s_dim_ic[incidentes_total], 0.84)
RETURN CALCULATE(COUNTROWS(s_dim_ic), s_dim_ic[incidentes_total] >= Corte)

% ICs Críticos = DIVIDE([ICs Críticos (top 16%)], COUNTROWS(s_dim_ic))

% Volume dos Críticos =
VAR Corte = PERCENTILE.INC(s_dim_ic[incidentes_total], 0.84)
RETURN DIVIDE(
    CALCULATE(SUM(s_dim_ic[incidentes_total]), s_dim_ic[incidentes_total] >= Corte),
    SUM(s_dim_ic[incidentes_total])
)

Gravidade Média = AVERAGE(s_dim_ic[grav_r3])

Gravidade Média dos Críticos =
VAR Corte = PERCENTILE.INC(s_dim_ic[incidentes_total], 0.84)
RETURN CALCULATE(AVERAGE(s_dim_ic[grav_r3]), s_dim_ic[incidentes_total] >= Corte)
```

**"Crítico" é uma definição criada no modelo**, não um atributo do dado: é o IC no percentil
84 ou acima de `incidentes_total`. Na prática o corte cai em **8 incidentes**. Por empates
em cima do corte, o resultado é 17,1% dos ICs e não exatos 16%.

#### A régua de gravidade

`grav_r3` é o índice de gravidade do IC no **regime 3**, definido na `s_dim_ic_regime` como
média ponderada da prioridade reescalada para 100–300:

| Valor | Significa |
|---|---|
| 300 | todos os incidentes do IC foram P2 |
| 200 | todos P3 |
| 100 | todos P4 |

P1 e P5 ficam fora da conta. Os cartões traduzem o número para a faixa:

```dax
Faixa da Gravidade =
VAR G = AVERAGE(s_dim_ic[grav_r3])
RETURN IF(ISBLANK(G), BLANK(),
    SWITCH(TRUE(),
        G >= 250, "≈ P2 (alta)",
        G >= 150, "≈ P3 (média)",
        "≈ P4 (baixa)"))
```

`Faixa da Gravidade dos Críticos` é a mesma lógica com o filtro de corte aplicado antes.

#### Os números que essa página produz

| Grupo | Nº de ICs | Gravidade média |
|---|---|---|
| Todos (é o cartão) | 6.386 | 231,08 |
| Só os críticos | 1.445 | 190,20 |
| Só os não críticos | 4.941 | 243,03 |
| Ponderada por incidentes | — | 157,68 |

`AVERAGE` ignora nulo, e `grav_r3` é nulo para 30,4% dos ICs — os que não tiveram atividade
no R3. A média é sobre os 6.386 ICs ativos no regime 3, não sobre os 9.171 da base.

### Gráficos

| Gráfico | Eixo | Valores | Cor |
|---|---|---|---|
| Itens de configuração por perfil de evolução | `s_dim_ic[perfil_evolucao]` | `Quantidade de ICs` | `Cor Perfil (barras)` |
| ICs por jornada de monitoramento | `s_dim_ic[jornada_monitoramento]` | `Quantidade de ICs` | tema |

```dax
Quantidade de ICs = COUNTROWS(s_dim_ic)
```

Domínio de `perfil_evolucao`, calculado na silver a partir de `delta_grav_r3_r2`:
`Agravou em R3` (delta > 15) · `Aliviou em R3` (delta < −15) · `Estável` · `Sem comparação`
(o IC não existia nos dois regimes).

Domínio de `jornada_monitoramento`, tradução da assinatura de 3 caracteres:
`Monitorado nativo novo` · `Monitorado nativo antigo` · `Migrado no R2` · `Migrado no R3` ·
`Sempre manual` · `Oscilante (termina monitorado)` · `Regrediu para manual`.

### Tabela — ICs por volume de incidentes

| Coluna exibida | Campo | Agregação |
|---|---|---|
| IC | `s_dim_ic[ic]` | — |
| Incidentes | `s_dim_ic[incidentes_total]` | Soma |
| Perfil de evolução | `s_dim_ic[perfil_evolucao]` | — |
| Jornada de monitoramento | `s_dim_ic[jornada_monitoramento]` | — |
| Duração mediana (h) | `s_dim_ic[duracao_mediana_h]` | Média |
| Times distintos | `s_dim_ic[times_distintos]` | Média |
| Dias desde o último | `s_dim_ic[dias_desde_ultimo]` | Média |

Como cada linha é um IC, Soma e Média devolvem o mesmo valor na linha; a diferença aparece
só no total. Média foi escolhida onde somar não faria sentido (somar "dias desde o último"
de 9 mil ICs não significa nada).

A coluna **Perfil de evolução** recebe cor de fundo e cor de fonte por medida, com a mesma
paleta do gráfico ao lado — ver [Apêndice A](#9-apêndice-a--medidas-de-cor).

---

## 7. Página 5 — Ruído

**Para que serve.** Transformar "65,8% é ruído" numa lista de alvos concretos: quais
templates e que tipo de alerta.

### Cartões

`% Ruído do Total`, `Incidentes Sem Intervenção` e `Total Incidentes` — as três já definidas
na página 1.

### Gráfico — Incidentes sem intervenção ao longo do tempo

| Papel | Campo |
|---|---|
| Eixo | `s_dim_calendario[data]` (grão diário) |
| Valores | `Sem Intervenção (todas)`, `Sem Intervenção P2`, `P3`, `P4` |

```dax
Sem Intervenção (todas) =
IF(NOT ISCROSSFILTERED(dim_prioridade), [Incidentes Sem Intervenção])

Sem Intervenção P2 =
IF(
    ISCROSSFILTERED(dim_prioridade) && 2 IN VALUES(dim_prioridade[prioridade]),
    CALCULATE([Incidentes Sem Intervenção], KEEPFILTERS(dim_prioridade[prioridade] = 2))
)
```

Quatro séries que **se excluem**: sem filtro de prioridade só a linha "todas" tem valor; com
filtro, só as linhas das prioridades selecionadas. É assim que a cor da linha muda conforme o
filtro sem precisar de um segundo visual.

### Gráfico — Top 10 templates por incidentes sem intervenção

| Papel | Campo |
|---|---|
| Eixo | `s_dim_template[template_descricao]` |
| Valores | `Sem Intervenção por Template` |
| Cor | `Cor Template Ruído (verde)` |
| Filtro | Top 10 por valor |

```dax
Sem Intervenção por Template =
SUMX(s_dim_template, s_dim_template[incidentes] * s_dim_template[pct_sem_intervencao] / 100)
```

Reconstrução por produto: a dimensão guarda o total de incidentes do template e o percentual
sem intervenção; a medida multiplica um pelo outro linha a linha.

> Consequência: esta medida **não responde ao filtro de data nem ao de prioridade**, porque
> lê colunas consolidadas da dimensão, não o fato diário.

### Gráfico — Que tipo de alerta é o ruído

| Papel | Campo |
|---|---|
| Eixo | `dim_classe[classe_descricao]` |
| Valores | `Ruído por Classe` |
| Cor | `Cor Ruído Classe (verde)` |

```dax
Ruído por Classe =
CALCULATE([Incidentes por Classe], s_fato_diario_classe[tipo_tratamento] = "sem_intervencao")
```

Herda toda a lógica de prioridade de `Incidentes por Classe` e acrescenta o recorte de
tratamento. Responde ao filtro de data e ao de prioridade.

---

## 8. Página 6 — OLA

**Para que serve.** Mostrar a consequência operacional: o acordo de nível de serviço já caiu
de faixa em P2, e o backlog é o indicador que avisa antes.

### O padrão de foto do último dia

Quatro medidas usam a mesma estrutura — tirar o valor **do último dia do período filtrado**,
não a média do período:

```dax
OLA Duração (%) =
VAR d = MAX(s_fato_ola_prioridade[data])
RETURN CALCULATE(AVERAGE(s_fato_ola_prioridade[atingimento_ola_duracao]),
                 s_fato_ola_prioridade[data] = d)
```

Mesmo padrão em `OLA Volume (%)`, `Violações OLA no Ano` (sobre
`kpi_violado_prioridade_ac_ano`) e `Fechados no Ano (OLA)` (sobre
`fechados_prioridade_ac_ano`). Por isso o título da tabela diz *"último dia do período"* —
mudar o filtro de data muda qual dia é fotografado.

### A escada de faixas

```dax
Violações até Cair de Faixa =
VAR p = SELECTEDVALUE(dim_prioridade[prioridade])
VAR v = [Violações OLA no Ano]
VAR lim = SWITCH(p,
    2, SWITCH(TRUE(), v <= 30, 30, v <= 35, 35, v <= 39, 39, v <= 45, 45, v <= 53, 53),
    3, SWITCH(TRUE(), v <= 200, 200, v <= 230, 230, v <= 263, 263, v <= 290, 290, v <= 320, 320))
RETURN IF(NOT ISBLANK(lim), lim - v + 1)
```

Os degraus são **constantes escritas na medida** — vêm da regra de negócio do OLA, não do
dado. Para P2: 30 / 35 / 39 / 45 / 53. Para P3: 200 / 230 / 263 / 290 / 320. A medida acha o
próximo degrau acima do acumulado atual e devolve quantas violações faltam para alcançá-lo.

O degrau de **39 (P2)** e **263 (P3)** é o que derruba o atingimento abaixo de 100%.

### O porteiro do histórico

```dax
Ano com Dados de OLA =
CALCULATE(SUM(s_fato_ola_prioridade[fechados_prioridade]),
          ALL(s_dim_calendario),
          s_dim_calendario[ano] = YEAR(MAX(s_fato_ola_prioridade[data])))

OLA Duração Histórico = IF([Ano com Dados de OLA] > 0, [OLA Duração (%)])
```

Os quatro `… Histórico` (`OLA Duração`, `OLA Volume`, `Violações Acumuladas`, `Backlog`)
existem para **não desenhar linha em ano sem dado de OLA**. Sem esse porteiro, as séries
apareceriam como zero em 2023 e 2024.

Sobre eles ficam as variantes por prioridade, todas no mesmo molde:

```dax
OLA Duração P2 = CALCULATE([OLA Duração Histórico], KEEPFILTERS(dim_prioridade[prioridade] = 2))
Violações Acumuladas P2 = CALCULATE([Violações Acumuladas Histórico], KEEPFILTERS(dim_prioridade[prioridade] = 2))
Backlog P2 = CALCULATE([Backlog Histórico], KEEPFILTERS(dim_prioridade[prioridade] = 2))
```

### Backlog

```dax
Backlog em Aberto =
CALCULATE(SUM(s_fato_diario_prioridade[backlog]),
          s_fato_diario_prioridade[tipo_tratamento] = "com_intervencao")

Pico de Backlog em Aberto = MAXX(VALUES(s_dim_calendario[data]), [Backlog em Aberto])
```

Só conta `com_intervencao` — backlog de alerta que se resolve sozinho não é fila de trabalho.
O pico é o máximo diário dentro do período filtrado.

### Os quatro visuais

| Visual | Eixo | Valores |
|---|---|---|
| Tabela *Cumprimento de OLA por prioridade* | `dim_prioridade[Prioridade_Rotulo]` | `OLA Duração (%)`, `OLA Volume (%)`, `Violações OLA no Ano`, `Violações até Cair de Faixa`, `Fechados no Ano (OLA)`, `Pico de Backlog em Aberto` |
| Cartão de 4 valores | — | `OLA Duração P2`, `OLA Duração P3`, `OLA Volume P2`, `OLA Volume P3` |
| *Histórico do cumprimento por duração* | `s_dim_calendario[data]` | `OLA Duração P2`, `OLA Duração P3` |
| Matriz mensal | `s_dim_calendario[ano_mes]` | `OLA Duração P2/P3`, `OLA Volume P2/P3` |
| *Violações acumuladas no ano* | `s_dim_calendario[data]` | `Violações Acumuladas P2`, `P3` |
| *Backlog em aberto* | `s_dim_calendario[data]` | `Backlog P2`, `P3`, `P4` |

As células de OLA na tabela e no cartão recebem cor por medida — ver Apêndice A.

---

## 9. Apêndice A — medidas de cor

### Semáforo de OLA

```dax
Cor OLA Duração =
VAR x = [OLA Duração (%)]
RETURN SWITCH(TRUE(),
    ISBLANK(x), BLANK(),
    x >= 125, "#16A34A",   -- verde
    x >= 100, "#CA8A04",   -- amarelo
    "#DC2626")             -- vermelho
```

Existem quatro variantes com a mesma escada: `Cor OLA Duração`, `Cor OLA Volume` e as
versões `… P2` / `… P3`.

### Perfil de evolução do IC

Três medidas com a **mesma paleta**, para o gráfico e a tabela não divergirem:

```dax
Cor Perfil = Cor Perfil (barras) =
SWITCH(SELECTEDVALUE(s_dim_ic[perfil_evolucao]),
    "Agravou em R3",  "#DC2626",
    "Aliviou em R3",  "#16A34A",
    "Estável",        "#2563EB",
    "Sem comparação", "#CBD5E1",
                      "#CBD5E1")

Cor Perfil (texto) =
SWITCH(SELECTEDVALUE(s_dim_ic[perfil_evolucao]), "Sem comparação", "#1F2937", "#FFFFFF")
```

`Cor Perfil` pinta o fundo da célula, `Cor Perfil (barras)` pinta a barra,
`Cor Perfil (texto)` garante contraste da fonte sobre os fundos saturados.

### Rampa verde de classe e template

Três medidas com a mesma escada de cinco tons, ancorada no verde `#16A34A` do ícone do
Template Líder:

```dax
Cor Classe (verde) =
VAR V = [Incidentes por Classe]
VAR M = MAXX(ALLSELECTED(dim_classe[classe_descricao]), [Incidentes por Classe])
VAR R = DIVIDE(V, M)
RETURN SWITCH(TRUE(),
    R >= 0.80, "#14532D",
    R >= 0.55, "#166534",
    R >= 0.30, "#15803D",
    R >= 0.12, "#16A34A",
               "#86EFAC")
```

Variantes: `Cor Ruído Classe (verde)` (sobre `[Ruído por Classe]`) e
`Cor Template Ruído (verde)` (sobre `[Sem Intervenção por Template]`, com
`ALLSELECTED(s_dim_template[template_descricao])`).

O tom é relativo ao **maior valor visível**, não absoluto — então a barra líder é sempre a
mais escura, independentemente da escala.

### Degradê contínuo por ranking

`Cor Time (degradê)` interpola RGB entre dois extremos conforme a posição no ranking, e monta
o hexadecimal à mão com `MID` sobre a string `"0123456789ABCDEF"`:

```dax
VAR rk = RANKX(ALLSELECTED(dim_time[time]), [Incidentes por Time], , DESC, Dense)
VAR t  = IF(n <= 1, 1, 1 - (rk - 1) / (n - 1))
VAR R  = ROUND(196 + (76 - 196) * t, 0)   -- e assim para G e B
```

Ainda em uso no gráfico da página Times. As versões `Cor Classe (degradê)` e
`Cor Template Ruído (degradê)` foram substituídas pelas verdes.

---

## 10. Apêndice B — medidas sem uso atual

Existem no modelo e não são referenciadas por nenhum visual. Nenhuma quebra nada; ficam
listadas para não serem confundidas com medidas ativas.

| Medida | Situação |
|---|---|
| `% do Total` | nunca usada |
| `Frase Ruído` | **texto fixo** — `= "dos incidentes se resolvem sem ninguém agir"`. Não é cálculo |
| `Violações OLA no Período` | nunca usada |
| `Fechados até Cair de Faixa (volume)` | nunca usada |
| `Limite 100% P2 (39 violações)` | removida do gráfico de violações acumuladas |
| `Limite 100% P3 (263 violações)` | idem |
| `Cor Classe (degradê)` | substituída por `Cor Classe (verde)` |
| `Cor Template Ruído (degradê)` | substituída por `Cor Template Ruído (verde)` |

**Intermediárias** (usadas por outras medidas, nunca diretamente em visual):
`Share do Time`, `ICs Críticos (top 16%)`, `Backlog em Aberto`, `Ano com Dados de OLA`,
`OLA Duração Histórico`, `OLA Volume Histórico`, `Violações Acumuladas Histórico`,
`Backlog Histórico`.

---

## 11. Apêndice C — ressalvas conhecidas

**1. O filtro de data está salvo em 01/01/2025.** Nas seis páginas. Isso corta o R1 — que é
artefato de extração, 732 registros — mas também muda os números de tela: `Total Incidentes`
lê 121 Mil em vez de 122 Mil, e `% Ruído do Total` lê 66,2% em vez de 65,8%. Para o período
completo, arrastar para 02/01/2023 em cada página (as segmentações de data **não** são
sincronizadas).

**2. Medidas que ignoram os filtros da página.** Por lerem colunas consolidadas de dimensão,
e não o fato diário:

- `Template Líder %` e `Template Líder (nome)` — `s_dim_template[pct_volume]`
- `Sem Intervenção por Template` — `incidentes × pct_sem_intervencao`
- a matriz de mix por time — `dim_time[pct_p2/p3/p4]`
- tudo da página ICs — `s_dim_ic` não tem coluna de data

**3. `AVERAGE` ignora nulo.** `Gravidade Média` e `Gravidade Média dos Críticos` são médias
sobre os ICs com `grav_r3` preenchido (69,6% da base), não sobre os 9.171.

**4. "Crítico" é definição do relatório, não do dado.** Percentil 84 de `incidentes_total`,
recalculado no contexto de filtro vigente. Se alguém filtrar a página, o corte se move.

**5. A rotulagem de classe não é determinística.** `classe_descricao` vem de um LLM. A
estabilidade entre execuções vem do mapa `template → classe` congelado em
`s_dim_template.csv`, não do modelo.

**6. Navegação exige Ctrl + clique no Desktop.** Comportamento padrão do Power BI em modo de
edição, não do relatório. No Service, clique simples funciona.

---

## Fontes

- DAX extraído do modelo semântico do `Dashboard_Challenge_Locaweb.pbix` pela exibição TMDL
- Definição dos visuais lida dos JSON em `Report/definition/pages/`
- Domínios e regras de coluna: `1_bronze_data/data_dictionary.md` e `2_silver_data/data_dictionary.md`
