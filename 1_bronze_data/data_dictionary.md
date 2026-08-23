# Dicionário de dados — Bronze

Camada de entrada do projeto. É a base de incidentes entregue pela Locaweb após o tratamento
bronze (normalização de tipos e flags de validação). Nada aqui é derivado pelo notebook de
exploração — as derivações começam na camada silver.

**Fonte das definições:** `notebooks/data_exploration.ipynb`, §2.1 (`carregar_bronze`), §2.2
(`enriquecer_incidentes`) e o dicionário no topo do notebook.

---

## Arquivos

| Item | Valor |
|---|---|
| Pasta | `1_bronze_data/` |
| Objeto de dados | `b_incidentes.csv` — **é uma pasta**, não um arquivo |
| Partições | `part-00000-…csv` (76.918 linhas) e `part-00001-…csv` (45.625 linhas), cada uma com o próprio cabeçalho |
| Marcadores | `_SUCCESS`, `.crc` — resíduo da escrita Spark, ignorar |
| Total | **122.543 registros × 23 colunas** |
| Separador | `;` |
| Encoding | `ISO-8859-1` |
| Fuso das datas | UTC (sufixo `Z`); o notebook aplica `tz_localize(None)` antes de qualquer comparação com calendário |
| Sentinelas nulas | `N/A`, `""`, `" "`, `NaN`, `None`, `NAN`, `null`, `-` |

Leitura de referência (`OPCOES_LEITURA` no notebook):

```python
pd.read_csv(parte, sep=";", encoding="ISO-8859-1",
            parse_dates=["Aberto", "Resolvido", "Encerrado"],
            dtype={"Número": "string"}, na_values=SENTINELAS_NULAS)
```

O contrato de colunas é validado logo após a carga (`COLUNAS_ESPERADAS`): coluna ausente
interrompe a execução, coluna nova é apenas avisada.

---

## Cobertura temporal

| Campo | Mínimo | Máximo |
|---|---|---|
| `Aberto` | 2023-01-02 20:19 | 2025-12-31 23:45 |
| `Encerrado` | 2025-01-01 00:10 | 2025-12-31 23:45 |

`Encerrado` nunca é anterior a 01/01/2025. Isso confirma a regra de extração: a Locaweb entregou
os incidentes **abertos ou encerrados em 2025**. O que aparece em 2023/2024 são apenas os poucos
casos de vida longa que atravessaram o ano — 732 registros, 0,6 % da base. O notebook chama esse
período de **R1 (artefato)** e o descarta da modelagem.

---

## Chave

| Coluna | Tipo | Nulo | Distintos | Descrição |
|---|---|---|---|---|
| `Número` | string | 0 % | 122.543 | Identificador único do incidente (`INC…`). Sem duplicata. |

---

## Categóricas

| Coluna | Tipo | Nulo | Distintos | Descrição |
|---|---|---|---|---|
| `Prioridade` | object | 0 % | 5 | `1 - Crítica` (1) · `2 - Alta` (15.649) · `3 - Média` (41.732) · `4 - Baixa` (64.828) · `5 - Muito Baixa` (333). P1 e P5 são residuais e ficam fora do alvo. |
| `Status` | object | 0 % | 4 | `Sem Intervenção` (80.373) · `Encerrado Automaticamente` (26.830) · `Encerrado` (15.339) · `Aguardando Problema` (1). **Coluna de origem de `tipo_tratamento`.** |
| `Aberto por` | object | 0 % | 2 | `Monitoramento` (104.299) · `Manual` (18.244). |
| `Grupo designado` | object | 0 % | 17 | Time responsável (`Team01`…). São 17 valores distintos contra 14 times informados pela área — divergência ainda em aberto (§3.5). `Team14` responde por 92.775 registros (75,7 %). |
| `Item de configuração` | object | 1,5 % | 9.171 | Ativo afetado (`IC00001`…). Nulo vira `SEM_IC` na silver, com a flag `ic_ausente`. |
| `Descrição Resumida` | object | 0 % | 17.787 | Texto do alerta. ~7 incidentes por texto único: é **gerado por template**, não escrito por pessoa. A silver extrai o template em `template_descricao` (13.317 distintos). |
| `Categoria` | object | 63,4 % | 141 | Classificação funcional. |
| `Subcategoria` | object | 63,4 % | 447 | Detalhamento da categoria. |
| `Produto` | object | 63,6 % | 51 | Produto afetado. |
| `Solução` | object | 87,5 % | 2 | `Contorno` (9.407) · `Definitiva` (5.893). |
| `Incidente Pai` | object | 87,7 % | 3.326 | Vínculo com o incidente-pai, quando o ticket faz parte de um evento maior. |

> **`Status` é a coluna mais importante da base nesta revisão.** É dela que sai a dimensão que
> separa o alvo em duas séries por prioridade. A leitura correta **não** é "encerrado
> automaticamente = sem gente": `Encerrado Automaticamente` é chamado tratado que o fluxo fechou
> sozinho depois, e conta como **com** intervenção. Só `Sem Intervenção` é alerta que nasce e
> morre na máquina.
>
> ```python
> tipo_tratamento = "sem_intervencao" if Status == "Sem Intervenção" else "com_intervencao"
> # 80.373 sem_intervencao / 42.170 com_intervencao
> ```

> **O bloco `Categoria` / `Subcategoria` / `Produto`** tem ~63 % de nulo e nulidade praticamente
> idêntica (77.719 / 77.720 / 77.935). Não é ausência aleatória: é um subconjunto de incidentes
> que não passa por classificação. A silver marca esses casos com `sem_classificacao`.

---

## Temporais

Todas em UTC, formato `YYYY-MM-DDThh:mm:ss.sssZ`.

| Coluna | Nulo | Descrição |
|---|---|---|
| `Aberto` | 0 % | Abertura do incidente. **É o grão temporal do alvo** — todas as contagens de `abertos` na silver são por data de abertura. |
| `Resolvido` | 67,2 % | Resolução técnica. Nulo quando o ticket fecha sem passar por resolução formal (o caso da maioria dos alertas automáticos). |
| `Encerrado` | 0 % | Fechamento administrativo. É o grão das contagens de `fechados` na silver. |

---

## Numéricas

| Coluna | Tipo | Nulo | Unidade | Descrição |
|---|---|---|---|---|
| `Duração` | int64 | 0 % | segundos | Tempo entre abertura e encerramento. Mediana 978 s (~16 min), média 248.547 s — distribuição fortemente assimétrica, máximo de 8,8×10⁷ s (≈ 24.522 h). A silver deriva `duracao_horas = Duração / 3600` e usa **mediana e p90**, nunca média. |
| `Tempo_Pos_Resolução` | float64 | 67,2 % | segundos | Intervalo entre resolução e encerramento. Nulo exatamente onde `Resolvido` é nulo. |
| `Diferença_Limite_Duração` | int64 | 0 % | segundos | Distância até o limite de duração do KPI. Negativo = dentro do limite; positivo = estourou. Mediana −60.887 s. |

---

## Flags de KPI

| Coluna | Nulo | Valores | Descrição |
|---|---|---|---|
| `Entrou para KPI?` | 0 % | `SIM` (25.602) / `NAO` (96.941) | Se o incidente entra no cálculo de OLA. |
| `KPI Violado?` | 79,1 % | `SIM` (248) / `NAO` (25.354) | Violação do limite. Nulo exatamente nos 96.941 que não entraram para KPI — a ausência é estrutural, não perda de dado. |

---

## Flags de validação (geradas no tratamento bronze)

| Coluna | Tipo | Verdadeiros | Descrição |
|---|---|---|---|
| `Resolvido_after_Encerrado` | bool | 32 | Resolução posterior ao encerramento — inconsistência de ordenação. |
| `Duração_is_inconsistent` | bool | 497 | `Duração` não bate com a diferença entre as datas. |
| `Modified_Record` | bool | 13 | Registro alterado pelo tratamento bronze. |

Volumes baixos o bastante para não exigirem exclusão, mas os registros ficam marcados. O notebook
os imprime na checagem de sanidade de §2.2.

---

## O que a silver acrescenta a este grão

Derivações criadas por `enriquecer_incidentes()` e que não existem no arquivo bronze:

| Coluna derivada | Regra |
|---|---|
| `data`, `data_encerrado`, `data_resolvido` | as três temporais normalizadas para meia-noite, sem fuso |
| `prioridade` | `Prioridade` mapeada para inteiro 1–5 |
| `hora_abertura`, `hora_encerramento` | hora cheia das respectivas datas |
| `turno`, `turno_encerramento` | `madrugada` 0–6 · `manha` 6–12 · `tarde` 12–18 · `noite` 18–24 |
| `horario_comercial` | hora de abertura entre 8 e 18 |
| `duracao_horas` | `Duração / 3600` |
| `aberto_por_monitoramento` | `Aberto por == "Monitoramento"` |
| `sem_intervencao` | `Status == "Sem Intervenção"` (flag 0/1, consumida como média nas `dim_*`) |
| `tipo_tratamento` | versão categórica da flag acima — **a dimensão que separa as 6 séries alvo** |
| `kpi_violado`, `entrou_kpi` | `== "SIM"` |
| `ic`, `ic_ausente` | `Item de configuração` com nulo preenchido por `SEM_IC` |
| `sem_classificacao` | `Produto`, `Categoria` e `Subcategoria` todos nulos |
| `regime` | `1` antes de 2025-01-01 · `2` antes de 2025-09-03 · `3` a partir daí |
| `template_descricao` | `Descrição Resumida` com IP/host/ID/número/data mascarados (§2.9) |
| `classe_descricao` | classe de negócio do template, rotulada por LLM sobre 95 % do volume |

Ver `2_silver_data/data_dictionary.md` para as tabelas resultantes.
