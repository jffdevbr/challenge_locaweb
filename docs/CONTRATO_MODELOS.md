# Contrato de serving dos modelos

Fonte da verdade para qualquer código que consuma `models/`. Escrito para dispensar a leitura de
`notebooks/model_training.ipynb` (3,7 MB) — o que este documento afirma foi extraído de lá (§7.2 e
§12.4) e **verificado contra `3_gold_data/g_previsoes.csv`**.

---

## 1. O que são os artefatos

18 arquivos em `models/`, mais `manifesto.csv`:

```
{tipo_tratamento}_P{prioridade}_{D1|D7}_{ARIMA|SARIMA}.pkl
```

3 grupos × 3 prioridades × 2 horizontes. O vencedor de cada `grupo × horizonte` serve as 3
prioridades, mas **cada prioridade tem o seu próprio ajuste** — mesma família, parâmetros
diferentes.

Todos são `statsmodels.tsa.statespace.sarimax.SARIMAXResultsWrapper`, gravados com
`ajuste.save(caminho)`. Nesta safra **nenhum Prophet e nenhum LSTM foi escolhido**, então servir
não precisa de `torch`, `prophet`, `cmdstanpy`, `xgboost` nem `scikit-learn`.

Os parâmetros dentro do artefato estão **congelados no treino**. Quem serve não reajusta: refiltra
o estado com o dado real disponível até a origem.

`manifesto.csv` (`sep=";"`) amarra cada arquivo à linha de `g_avaliacao_modelos` que o justifica —
`mae`, `mase`, `mae_ingenuo`, `ganho_vs_ingenuo`, `supera_ingenuo`, `regra_ingenua`,
`ajustado_ate`, `corte_teste`, `n_treino`, `configuracao`.

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

Só as famílias `SARIMA` recebem exógenas, e só de calendário:

| Horizonte | Colunas | Origem |
|---|---|---|
| `D+1` | `feriado`, `vespera_feriado`, `pos_feriado` | `s_dim_calendario.csv` |
| `D+7` | `feriados_7d`, `vesperas_7d` | derivadas do calendário (janela retroativa D-6..D) |

Os `.pkl` foram ajustados com `numpy.ndarray`, então **não carregam os nomes das colunas** —
`res.model.exog_names` devolve `x1, x2, ...`. A ordem é a da tabela acima, e a verificação correta
é cruzar `res.model.k_exog` com o mapa de exógenas do horizonte, na **carga**, não na requisição.

Nesta safra apenas `com_intervencao_P*_D1_SARIMA` usa exógenas (`k_exog = 3`); os outros 15 são
ARIMA puro com `k_exog = 0`.

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

```python
import statsmodels.api as sm

res = sm.load(caminho_pkl)                      # parâmetros congelados no treino

previsao = (
    res.apply(historico_ate_D, exog=exog_ate_D, refit=False)   # refiltra o estado
       .forecast(steps=passos, exog=exog_futuro)               # exog_futuro = D+1..D+passos
)[-1]                                                          # o ÚLTIMO passo é a previsão

previsao = max(float(previsao), 0.0)            # contagem não é negativa
```

`refit=False` é o ponto todo: os parâmetros não se movem, só o estado do filtro de Kalman avança
com o dado real. Se o `apply` levantar exceção ou devolver valor não finito, o fallback do notebook
é o último valor observado da série.

Intervalo de previsão, quando necessário:

```python
proj = res.apply(historico_ate_D, exog=exog_ate_D, refit=False) \
          .get_forecast(steps=passos, exog=exog_futuro)
inferior, superior = proj.conf_int(alpha=0.20)[-1]      # banda de 80 %
```

### Verificado

Reproduzido contra `g_previsoes.csv` (filtro `escolhido = True`) com diferença máxima de **0,005**,
que é o arredondamento de 2 casas do próprio arquivo. É o teste de `tests/test_reproducao.py`.

---

## 8. O resultado, sem maquiagem

| Grupo | Horizonte | Vencedor | MAE | MAE ingênuo | Supera o ingênuo? |
|---|---|---|---|---|---|
| `com_intervencao` | D+1 | SARIMA | 16,21 | 15,87 | ❌ −2,2 % |
| `com_intervencao` | D+7 | ARIMA | **58,20** | 91,90 | ✅ **+36,7 %** |
| `sem_intervencao` | D+1 | ARIMA | 85,83 | 54,13 | ❌ −58,6 % |
| `sem_intervencao` | D+7 | ARIMA | 563,14 | 458,86 | ❌ −22,7 % |
| `total` | D+1 | ARIMA | 82,21 | 59,21 | ❌ −38,8 % |
| `total` | D+7 | ARIMA | 555,80 | 462,97 | ❌ −20,1 % |

**1 de 6 supera o baseline ingênuo.** Recomendação de negócio registrada em
`3_gold_data/data_dictionary.md`: usar o modelo em produção onde ele ganha — hoje,
`com_intervencao` em D+7 — e o próprio ingênuo como referência operacional nos demais.

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
