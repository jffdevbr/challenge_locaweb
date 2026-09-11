# Contrato de serving dos modelos

Fonte da verdade para qualquer código que consuma `models/`. Escrito para dispensar a leitura de
`notebooks/model_training.ipynb` (3,7 MB) — o que este documento afirma foi extraído de lá (§7.2 e
§12.4) e **verificado contra `3_gold_data/g_avaliacao_modelos.csv` e `models/manifesto.csv`**.

> ⚠️ **O contrato mudou nesta safra — `api/` ainda não foi atualizada para ele.** A safra anterior
> exportava só `SARIMAXResultsWrapper` em pickle. Esta exporta **três famílias**, e 10 dos 18
> artefatos não são mais pickle de statsmodels. Qualquer código de serving escrito contra a safra
> anterior vai carregar 8 dos 18 arquivos e falhar silenciosamente nos outros 10 se não tratar
> `.json`. Ver §1 e §7.

---

## 1. O que são os artefatos

18 arquivos em `models/`, mais `manifesto.csv` e, para os que não são SARIMAX, um sidecar
`.config.json`:

```
{tipo_tratamento}_P{prioridade}_{D1|D7}_{SARIMAX|ETS|Theta}.{pkl|json}
{tipo_tratamento}_P{prioridade}_{D1|D7}_{SARIMAX|ETS|Theta}.config.json    # sidecar
```

3 grupos × 3 prioridades × 2 horizontes = 18 séries, **cada uma com o seu próprio vencedor** —
famílias e parâmetros diferentes por série, não mais um vencedor por `grupo × horizonte` servindo
as 3 prioridades. Contagem real desta safra: **8 `SARIMAX`, 7 `Theta`, 3 `ETS`**.

| Família | Extensão | Como é gravado | Como se reconstrói |
|---|---|---|---|
| `SARIMAX` | `.pkl` | `statsmodels.tsa.statespace.sarimax.SARIMAXResultsWrapper`, via `ajuste.save(caminho)` | `sm.load(caminho)` — igual à safra anterior |
| `ETS` | `.json` | Parâmetros do `ETSModel` ajustado, mais a especificação (`trend`, `damped_trend`, `seasonal`, `seasonal_periods`) | `ETSModel(historico, ...).smooth(params)` — **não há pickle**; o histórico entra sempre por fora |
| `Theta` | `.json` | Só a configuração (`period`, `deseasonalize`) | `ThetaModel(historico, ...).fit()` a cada chamada — **não há estado a carregar**, o método é fechado e reajusta toda vez |

Nenhum Prophet e nenhum LSTM foi escolhido nesta safra — as duas famílias competiram só como
referência no hold-out, fora da disputa por validação (ver `data_dictionary.md`). Servir não
precisa de `torch`, `prophet`, `cmdstanpy`, `xgboost` nem `scikit-learn` — mas **precisa agora do
`ETSModel` e do `ThetaModel` do statsmodels**, já presentes em `requirements_api_container.txt`
porque a versão do statsmodels é pinada entre notebooks e API (ver CLAUDE.md).

Os parâmetros dentro do artefato SARIMAX/ETS estão **congelados no treino**. Quem serve não
reajusta: refiltra o estado com o dado real disponível até a origem. O Theta não tem esse conceito
— cada chamada de serving reajusta com o histórico completo até a origem, porque é isso que o
notebook faz na avaliação (§7.2).

`manifesto.csv` (`sep=";"`) amarra cada arquivo à linha de `g_avaliacao_modelos` que o justifica —
`familia`, `transformacao`, `exog`, `mae_cv`, `mae`, `mase`, `mae_ingenuo`, `ganho_vs_ingenuo`,
`supera_ingenuo`, `regra_ingenua`, `ajustado_ate`, `corte_teste`, `n_treino`, `n_blocos_cv`,
`configuracao`. As colunas `mae_cv` e `n_blocos_cv` são novas: `mae_cv` é o critério que escolheu
o modelo (o MAE do backtest de origem móvel, nunca o do teste); `mae` continua sendo o resultado
medido no hold-out, que não participou da escolha.

---

## 2. Os dois horizontes

Os dois são previstos de forma **direta**, cada um com o seu próprio modelo ajustado sobre a sua
própria série. Não há recursão.

| Horizonte | Série alvo | Passos | Significado da previsão |
|---|---|---|---|
| `D+1` | `abertos` | 1 | contagem do dia `D+1` |
| `D+7` | `soma7` | 7 | acumulado de `D+1` a `D+7` |

`soma7` é a soma móvel de 7 dias fechando em `D`. A identidade que sustenta o horizonte longo:

```
soma7(D)   = abertos[D-6] + ... + abertos[D]
soma7(D+7) = abertos[D+1] + ... + abertos[D+7]   = y_abertos_acum_1a7(D)
```

Prever `soma7` sete passos à frente **é** o acumulado da semana. A previsão é o **último** passo da
projeção; os passos intermediários existem só porque o filtro precisa deles e não viram previsão.

---

## 3. Exógenas

Só a família `SARIMAX` recebe exógenas, e a lista **varia por série** — não é mais um conjunto
fixo por horizonte. Cada série passou por uma seleção progressiva (até 3 colunas, cada uma só
entra se reduzir o MAE de validação além do próprio ruído), então a lista de exógenas de uma
série não prevê a de outra.

Dois blocos de candidatas possíveis:

| Tipo | Exemplos | Defasagem |
|---|---|---|
| Calendário | `feriado`, `vespera_feriado`, `pos_feriado`, `dia_util`, `fim_de_semana`, `sen_semana`, `cos_semana` (D+1); `feriados_7d`, `vesperas_7d`, `dias_uteis_7d`, `sen_ano`, `cos_ano` (D+7) | nenhuma — conhecido para qualquer data futura |
| Estado observado em D | `backlog`, `fechados`, `saldo_aberto_fechado`, `inc_por_ic`, `inc_por_descricao`, `inc_por_time`, `ics_distintos`, `times_distintos`, `descricoes_distintas`, `soma7` | **defasada de `h` dias** (sufixo `_obs1` ou `_obs7`) — a linha D+k carrega o valor de D+k−h, que nunca é posterior à origem |

**A lista efetiva de cada série está em `manifesto.csv`, coluna `exog`** (vazia = `-`), e replicada
no sidecar `.config.json` de cada artefato. Não assumir nenhuma lista fixa: ler o sidecar antes de
montar a matriz de exógenas.

Os `.pkl` foram ajustados com `numpy.ndarray` padronizado (centralizado e escalado pela janela de
treino), então **não carregam os nomes das colunas nem a escala** — `res.model.exog_names` devolve
`x1, x2, ...`. O sidecar carrega `exog` (ordem), `exog_centro` e `exog_escala`: a exógena bruta
tem de ser padronizada como `(valor - centro) / escala`, na mesma ordem, antes de entrar no
`forecast`. A verificação correta é cruzar `res.model.k_exog` com `len(exog)` do sidecar, na
**carga**, não na requisição.

Nesta safra, das 8 séries `SARIMAX`, 6 usam exógenas (1 a 3 cada) e 2 não usam nenhuma — ver
`manifesto.csv`.

---

## 4. Montagem das séries — obrigatória e nesta ordem

Errar qualquer passo faz a previsão não bater com a camada gold.

1. **`soma7` sobre o histórico inteiro**, desde 2023-01-02, e **só depois** recortar na janela do
   grupo:
   `soma7 = abertos.rolling(7, min_periods=7).sum()`.
   Recortar antes faria a série nascer com 6 dias nulos e perder a primeira semana da janela.
2. **Grupo `total`** = soma de `abertos` das duas fatias de `tipo_tratamento`, por
   `data × prioridade`. Não é uma terceira categoria do dado. As razões `inc_por_ic`,
   `inc_por_descricao` e `inc_por_time` são reconstruídas de **numerador e denominador somados
   antes de dividir** — somar duas razões não significa nada.
3. **Calendário de janela retroativa**: `x_7d = soma de x.shift(k) para k em 0..6`, fechando em `D`.
   É o calendário que corresponde ao ponto de `soma7(D)`.

---

## 5. Janelas, cortes e regimes — literais, não recalcular

| Grupo | Janela da série | Corte de teste | Último dia |
|---|---|---|---|
| `com_intervencao` | 2025-01-01 → 2025-12-31 | **2025-11-20** | 2025-12-31 |
| `sem_intervencao` | 2025-09-01 → 2025-12-31 | **2025-12-04** | 2025-12-31 |
| `total` | 2025-09-01 → 2025-12-31 | **2025-12-04** | 2025-12-31 |

O corte é o primeiro dia do teste. Treino é `data < corte`; teste é `data >= corte`.

Regimes (coluna `regime` das tabelas silver):

| Regime | Período | O que é |
|---|---|---|
| 1 | até 2024-12-31 | artefato de extração — **descartado da modelagem** |
| 2 | 2025-01-01 → 2025-08-31 | pré-automação |
| 3 | a partir de 2025-09-01 | pós-automação (quebra estrutural do pipeline de monitoramento) |

`sem_intervencao` e `total` começam em 2025-09-01 por causa dessa quebra: antes dela o grupo não
tem o comportamento que o modelo aprendeu.

---

## 6. Amostras: embargo e origens elegíveis

O alvo do `D+7` é uma **janela**, não um ponto, e isso corta as duas fronteiras:

- **Embargo no fim do treino** (*purged split*): a origem `D` só é amostra de treino se
  `D + passos` ainda for dia de treino. No `D+7` isso descarta as **6 últimas** origens antes do
  corte; no `D+1`, nenhuma. Treinar nelas seria vazamento — e vazamento que não aparece como erro,
  aparece como resultado bom demais.
- **Falta de real no fim da série**: uma origem só é ponto de teste se `D + passos` existe na
  série. O `D+7` perde as 6 últimas origens do teste.

Origem de teste, formalmente: `data[D+1] >= corte` **e** `D + passos <= último dia`.

---

## 7. Como servir

O caminho depende da família — ler `familia` (ou a extensão do arquivo) no `manifesto.csv` antes
de decidir como carregar.

### SARIMAX

```python
import statsmodels.api as sm

res = sm.load(caminho_pkl)                      # parâmetros congelados no treino
exog_ate_D = (exog_bruta_ate_D - centro) / escala      # de config["exog_centro"/"exog_escala"]
exog_futuro = (exog_bruta_futura - centro) / escala    # mesma padronização, mesma ordem

previsao = (
    res.apply(historico_ate_D, exog=exog_ate_D, refit=False)   # refiltra o estado
       .forecast(steps=passos, exog=exog_futuro)               # exog_futuro = D+1..D+passos
)[-1]                                                          # o ÚLTIMO passo é a previsão

if config["transformacao"] == "log1p":
    previsao = np.expm1(previsao)               # desfazer a transformação, se houver

previsao = max(float(previsao), 0.0)            # contagem não é negativa
```

`refit=False` é o ponto todo: os parâmetros não se movem, só o estado do filtro de Kalman avança
com o dado real. **A padronização das exógenas e a transformação da série não estão no `.pkl`** —
vêm do sidecar `.config.json` (§1, §3) e esquecê-las produz previsão sistematicamente errada, sem
erro nenhum na chamada.

### ETS

```python
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

cfg = json.load(open(caminho_json))
y = np.log1p(historico_ate_D) if cfg["transformacao"] == "log1p" else historico_ate_D

modelo = ETSModel(y, error=cfg["error"], trend=cfg["trend"],
                  damped_trend=cfg["damped_trend"], seasonal=cfg["seasonal"],
                  seasonal_periods=cfg["seasonal_periods"])
previsao = modelo.smooth(cfg["params"]).forecast(steps=passos)[-1]
if cfg["transformacao"] == "log1p":
    previsao = np.expm1(previsao)
previsao = max(float(previsao), 0.0)
```

Não há pickle: o histórico entra sempre de fora, e `smooth(params)` reconstrói o estado do filtro
sem reajustar os parâmetros — o equivalente do `refit=False` do SARIMAX para esta família.

### Theta

```python
from statsmodels.tsa.forecasting.theta import ThetaModel

cfg = json.load(open(caminho_json))
y = np.log1p(historico_ate_D) if cfg["transformacao"] == "log1p" else historico_ate_D

previsao = ThetaModel(y, period=cfg["period"], deseasonalize=cfg["deseasonalize"],
                      use_test=False).fit().forecast(steps=passos)[-1]
if cfg["transformacao"] == "log1p":
    previsao = np.expm1(previsao)
previsao = max(float(previsao), 0.0)
```

Não há estado a carregar — o método é fechado e **reajusta a cada chamada** sobre o histórico
completo. É mais caro por chamada que SARIMAX/ETS, mas nenhuma das 7 séries que o Theta venceu
tem volume que torne isso um problema de latência.

### Intervalo de previsão (só SARIMAX/ETS, que têm `get_forecast`)

```python
proj = res.apply(historico_ate_D, exog=exog_ate_D, refit=False) \
          .get_forecast(steps=passos, exog=exog_futuro)
inferior, superior = proj.conf_int(alpha=0.20)[-1]      # banda de 80 %
```

Com `log1p`, o intervalo é construído na escala transformada e trazido de volta com `expm1` nos
dois limites — quantil é equivariante a transformação monótona, então isso é exato.

### Trava de sanidade (todas as famílias)

Replicar no serving o teto que o treino usa para conter raiz explosiva ou extrapolação absurda:
`previsao = min(previsao, 2 * max(historico_ate_D[-28:]) + 10)`.

### ⚠️ Verificado só parcialmente — `api/` está desatualizada para este contrato

`tests/test_reproducao.py::test_manifesto_cobre_todo_o_grao` afirma
`modelos.meta(...)["modelo"] in ("ARIMA", "SARIMA")` — essa asserção **falha** contra o manifesto
atual, que tem `SARIMAX`, `ETS` e `Theta`. `api/previsao.py` foi escrita para a safra anterior e
não tem caminho de carga para `.json`. Antes de subir esta safra: (1) estender `api/previsao.py`
com os três blocos de código acima; (2) atualizar a asserção do teste; (3) rodar
`test_reproducao.py` de novo e confirmar a mesma tolerância de 0,01 nas 18 séries. Nenhum desses
três passos foi feito ainda.

---

## 8. O resultado, sem maquiagem

A unidade de decisão é a **série** (`grupo × prioridade × horizonte`), não mais o `grupo ×
horizonte`. **11 das 18 séries superam o baseline ingênuo** no hold-out — no critério agregado da
safra anterior isso seria 2 de 6:

| Grupo | Horizonte | MAE agregado (3 prioridades) | MAE ingênuo | Ganho agregado |
|---|---|---|---|---|
| `com_intervencao` | D+1 | **14,70** | 15,87 | ✅ **+7,4 %** |
| `com_intervencao` | D+7 | **63,84** | 91,90 | ✅ **+30,5 %** |
| `sem_intervencao` | D+1 | 56,33 | **54,13** | ❌ −4,1 % |
| `sem_intervencao` | D+7 | 548,97 | **458,86** | ❌ −19,6 % |
| `total` | D+1 | 59,62 | **59,21** | ❌ −0,7 % |
| `total` | D+7 | 521,75 | **462,97** | ❌ −12,7 % |

Detalhamento por série — quem venceu em cada prioridade e por quanto — está em
`3_gold_data/data_dictionary.md` §"O resultado, sem maquiagem" e em `models/manifesto.csv`.

**Recomendação de negócio, sem mudança de princípio: usar em produção apenas o modelo que supera o
ingênuo na sua série** — hoje, 11 das 18 — e a própria regra ingênua como referência operacional
nas outras 7, concentradas em P3 de `sem_intervencao`/`total`, cujo nível salta dentro da própria
janela de teste (limitação de dado, não de modelo).

Qualquer interface que sirva estes modelos deve mostrar esse fato ao lado da previsão, não
escondê-lo. As colunas `mae_ingenuo`, `ganho_vs_ingenuo` e `supera_ingenuo` do `manifesto.csv`
existem para isso.

---

## 9. Regras de OLA (contexto de negócio, fora do modelo)

Calibradas em `data_exploration.ipynb` §1, aplicadas sobre o **acumulado anual da prioridade
inteira** (as duas fatias de `tipo_tratamento` somadas) — nunca por tipo.

```python
ESCALA_OLA         = [150, 125, 100, 75, 50, 0]
FAIXAS_OLA_DURACAO = {2: [31, 36, 40, 46, 54],            3: [201, 231, 264, 291, 321]}
FAIXAS_OLA_VOLUME  = {2: [4585, 5389, 6169, 6253, 6337],  3: [19489, 22117, 22525, 23893, 24277]}

atingimento = ESCALA_OLA[np.searchsorted(cortes, acumulado, side="right")]
```

- **Duração** corre sobre `kpi_violado_prioridade_ac_ano`; **volume**, sobre
  `fechados_prioridade_ac_ano`. Mais acumulado = faixa pior.
- **P4 não tem faixa** em nenhuma das duas regras — é a origem dos 33,3 % de nulo de
  `s_fato_ola_prioridade`. Pendência aberta com a área.
- ⚠️ **As faixas de volume estão estouradas.** Em 31/12/2025 P2 fechou 15.649 contra um corte
  máximo de 6.337, e P3 fechou 41.732 contra 24.277: `atingimento_ola_volume` é 0 % o ano inteiro
  nas duas. As faixas foram calibradas para outra escala de volume e precisam de recalibração.
- A regra de **duração** é a que está viva: P3 cruzou o corte 201 em 2025-12-26 e caiu de 150 %
  para 125 % na virada de um dia.
