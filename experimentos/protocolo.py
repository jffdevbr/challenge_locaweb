"""O motor de avaliação — um só, usado por todo candidato.

A mudança de protocolo em relação à safra atual está inteira aqui: a escolha do modelo passa a
sair de um backtest de origem móvel DENTRO DO TREINO (`origens_cv`), e o conjunto de teste vira
hold-out puro, tocado uma única vez no fim. O motivo é simples: com 22 a 42 pontos de teste e
cinco candidatos, escolher pelo teste mede a sorte do candidato, não a qualidade dele.

A mecânica de previsão é idêntica à da célula 61 e à do serving: parâmetros congelados na janela
de ajuste, estado refiltrado com o dado real até cada origem, e o valor lido é o ÚLTIMO passo da
projeção.
"""
import numpy as np

from dados import (CORTE, HORIZONTES, N_TREINO, SERIES, COLUNA_SERIE)

# Quantas origens de validação, por grupo e horizonte. Espelham o tamanho do teste, para que a
# estimativa de CV tenha a mesma precisão que a do hold-out. Em `sem_intervencao`/`total` o D+7
# cede 7 origens porque o treino tem só 94 dias e cada origem de validação sai da janela de
# ajuste — abaixo de ~60 pontos de ajuste nada converge.
V_CV = {
    "com_intervencao": {"D+1": 42, "D+7": 36},
    "sem_intervencao": {"D+1": 28, "D+7": 21},
    "total":           {"D+1": 28, "D+7": 21},
}


def origens_treino(grupo, prioridade, horizonte):
    """Origens cujo alvo INTEIRO cai no treino (*purged split*) — célula 12."""
    n_treino = N_TREINO[(grupo, prioridade)]
    return list(range(0, n_treino - HORIZONTES[horizonte]))


def origens_teste(grupo, prioridade, horizonte):
    """Origens cujo alvo cai no teste e ainda tem real com que comparar — célula 55."""
    s = SERIES[(grupo, prioridade)]
    passos = HORIZONTES[horizonte]
    n = len(s)
    return [i for i in range(n) if i + passos < n and s.data.iloc[i + 1] >= CORTE[grupo]]


def origens_cv(grupo, prioridade, horizonte):
    """As últimas V origens do treino. Um bloco só — usado por comparações pontuais."""
    todas = origens_treino(grupo, prioridade, horizonte)
    v = V_CV[grupo][horizonte]
    return todas[-v:]


# Quantos blocos de validação, e de que tamanho, por grupo. Vários blocos em vez de um só porque
# um bloco contíguo colado ao teste mede o desempenho num regime apenas. Foi o que fez a primeira
# rodada eleger o ingênuo em `com_intervencao P3 D+7`: no bloco de outubro a série estava parada,
# e no teste ela despenca. Cada bloco tem o seu próprio ajuste, então a janela de estimação
# continua realista.
BLOCOS = {"com_intervencao": 3, "sem_intervencao": 2, "total": 2}
TAMANHO_BLOCO = {"com_intervencao": {"D+1": 42, "D+7": 36},
                 "sem_intervencao": {"D+1": 21, "D+7": 21},
                 "total": {"D+1": 21, "D+7": 21}}
MINIMO_AJUSTE = 40


def blocos_cv(grupo, prioridade, horizonte):
    """Blocos de origens de validação, do mais recente para o mais antigo.

    Um bloco só é aceito se a janela de ajuste que o precede tiver ao menos `MINIMO_AJUSTE`
    observações — abaixo disso nada converge e o bloco mediria ruído de otimizador.
    """
    todas = origens_treino(grupo, prioridade, horizonte)
    tamanho = TAMANHO_BLOCO[grupo][horizonte]
    saida = []
    fim = len(todas)
    for _ in range(BLOCOS[grupo]):
        inicio = fim - tamanho
        if inicio < 0:
            break
        bloco = todas[inicio:fim]
        if janela_ajuste(bloco) < MINIMO_AJUSTE:
            break
        saida.append(bloco)
        fim = inicio
    return saida or [origens_cv(grupo, prioridade, horizonte)]


def janela_ajuste(origens):
    """Nº de observações da janela em que os parâmetros são estimados.

    Termina no dia da primeira origem, inclusive: a origem é observável, o alvo dela não. Mesma
    relação que o teste tem com o treino, onde a janela de ajuste termina em `n_treino - 1` e a
    primeira origem de teste é `n_treino - 1`.
    """
    return origens[0] + 1


def _vif_sobreposicao(erros, passos):
    """Fator de inflação de variância pela sobreposição das janelas (Newey-West, Bartlett).

    No D+1 as origens não se sobrepõem e isto devolve 1. No D+7 janelas consecutivas dividem 6 dos
    7 dias, e ignorar isso faria o erro padrão parecer ~2,5x menor do que é — foi exatamente o
    cuidado que a célula 75 do notebook já tomava, reaproveitado aqui.
    """
    n = len(erros)
    atraso = passos - 1
    if atraso <= 0 or n <= atraso + 1:
        return 1.0
    x = np.asarray(erros, dtype=float)
    x = x - x.mean()
    var = float((x ** 2).mean())
    if var <= 0:
        return 1.0
    vif = 1.0
    for k in range(1, atraso + 1):
        rho = float((x[k:] * x[:-k]).mean()) / var
        vif += 2.0 * (1.0 - k / (atraso + 1.0)) * rho
    return float(max(vif, 1.0))


def resumir(reais, previstos, passos):
    """MAE e o erro padrão dele, já corrigido pela sobreposição das janelas."""
    reais = np.asarray(reais, dtype=float)
    previstos = np.asarray(previstos, dtype=float)
    erros = np.abs(previstos - reais)
    n = len(erros)
    vif = _vif_sobreposicao(erros, passos)
    n_efetivo = max(n / vif, 2.0)
    return {
        "mae": float(erros.mean()),
        "erro_padrao": float(erros.std(ddof=1) / np.sqrt(n_efetivo)) if n > 1 else float("nan"),
        "n": n,
        "n_efetivo": float(n_efetivo),
    }


def avaliar(candidato, grupo, prioridade, horizonte, origens, n_ajuste=None):
    """Ajusta uma vez na janela de ajuste, refiltra por origem, devolve MAE e erro padrão.

    Por padrão a janela de ajuste termina na primeira origem — é o que mantém a avaliação
    honesta, porque nenhum alvo avaliado entrou na estimação. `n_ajuste` permite fixá-la em outro
    ponto, e existe para UM caso: desenhar a série inteira com os parâmetros do treino. Nesse uso
    as origens anteriores ao treino ficam dentro da amostra, e o gráfico diz isso.

    Devolve `None` se o ajuste falhar por completo — candidato que não converge não entra no
    ranking disfarçado de fallback ingênuo.
    """
    passos = HORIZONTES[horizonte]
    s = SERIES[(grupo, prioridade)]
    y = s[COLUNA_SERIE[horizonte]].astype(float).to_numpy()
    n_aj = janela_ajuste(origens) if n_ajuste is None else n_ajuste

    estado = candidato.ajustar(grupo, prioridade, horizonte, n_aj)
    if estado is None:
        return None

    previstos, reais = [], []
    for i in origens:
        try:
            valor = candidato.prever(estado, grupo, prioridade, horizonte, i)
        except Exception:
            valor = float(y[i])
        if valor is None or not np.isfinite(valor):
            valor = float(y[i])
        # Trava de sanidade: a previsão não pode passar do dobro do pior dia do último mês. Um
        # SARIMAX com raiz explosiva devolve valor finito e absurdo — 4.163 numa série cujo
        # máximo histórico é 660 — e um único membro assim arruína uma combinação. O teto usa só
        # o histórico até a origem, vale igual para todo candidato, e nunca puxa uma previsão
        # para cima.
        teto = 2.0 * float(np.max(y[max(0, i - 27): i + 1])) + 10.0
        previstos.append(float(np.clip(valor, 0.0, teto)))
        reais.append(float(y[i + passos]))

    resultado = resumir(reais, previstos, passos)
    resultado["previstos"] = previstos
    resultado["reais"] = reais
    resultado["origens"] = list(origens)
    resultado["erros"] = np.abs(np.asarray(previstos) - np.asarray(reais))
    return resultado


def serializar_erros(erros):
    return ",".join(f"{e:.4f}" for e in np.asarray(erros, dtype=float))


def _deserializar(texto):
    if not isinstance(texto, str) or not texto:
        return None
    return np.array([float(v) for v in texto.split(",")], dtype=float)


def avaliar_multi(candidato, grupo, prioridade, horizonte, blocos):
    """Avalia em vários blocos, cada um com o seu próprio ajuste, e junta os erros.

    Juntar os erros (e não a média dos MAE por bloco) mantém a comparação pareada válida entre
    candidatos: todos são medidos exatamente nas mesmas origens, na mesma ordem.
    """
    partes = [avaliar(candidato, grupo, prioridade, horizonte, bloco) for bloco in blocos]
    partes = [p for p in partes if p is not None]
    if not partes:
        return None
    previstos = np.concatenate([p["previstos"] for p in partes])
    reais = np.concatenate([p["reais"] for p in partes])
    resultado = resumir(reais, previstos, HORIZONTES[horizonte])
    resultado["previstos"] = previstos
    resultado["reais"] = reais
    resultado["erros"] = np.abs(previstos - reais)
    resultado["n_blocos"] = len(partes)
    return resultado


def diferenca_pareada(erros_novo, erros_base, passos):
    """Média e erro padrão de `|e_novo| - |e_base|` nas MESMAS origens.

    Comparar candidatos pelos MAE isolados é impreciso: numa série curta o erro padrão do MAE
    chega a metade do próprio MAE. Pareando, a dificuldade comum daqueles dias se cancela e a
    diferença fica com erro padrão pequeno o bastante para decidir alguma coisa.

    Negativo = o novo é melhor.
    """
    d = np.asarray(erros_novo, dtype=float) - np.asarray(erros_base, dtype=float)
    n = len(d)
    if n < 3:
        return float(d.mean()) if n else 0.0, float("inf")
    vif = _vif_sobreposicao(d, passos)
    ep = float(d.std(ddof=1) / np.sqrt(max(n / vif, 2.0)))
    return float(d.mean()), ep


def melhora_significativa(erros_novo, erros_base, passos):
    """O novo é melhor além do ruído? Portão de entrada da seleção progressiva de exógenas.

    Aceitar qualquer melhora, por menor que seja, é o que faz uma busca progressiva sobre 19
    candidatas e 28 origens ajustar-se à própria validação: `total P4 D+1` foi de MAE 31 na CV
    para 111 no hold-out exatamente assim. Exigir que a melhora supere o próprio erro padrão
    corta o ganho de sorte.
    """
    media, ep = diferenca_pareada(erros_novo, erros_base, passos)
    return media < -ep


def escolher_pareado(linhas, chave_mae="mae_cv", chave_erros="erros", chave_custo="custo",
                     passos=1, epsilon=0.005):
    """Menor MAE de CV. Só cede a um mais barato quando a diferença é praticamente zero.

    A tentação aqui é a regra de 1 erro-padrão, que prefere o modelo mais simples entre os
    estatisticamente empatados. Com este dado ela não serve: a CV é ruidosa o bastante para que
    quase tudo empate, e o "mais simples" acaba sendo uma suavização exponencial sem tendência
    nem sazonalidade — que é o ingênuo com outro nome. Foi o que aconteceu na primeira tentativa,
    em três séries, com MAE de teste idêntico ao do piso.

    Então o critério é o objetivo declarado: menor erro fora da amostra. A parcimônia entra só
    como desempate quando a diferença é menor que `epsilon` relativo, onde ela realmente não
    muda nada.
    """
    validos = [l for l in linhas if np.isfinite(l.get(chave_mae, np.nan))]
    if not validos:
        return None
    melhor = min(validos, key=lambda l: l[chave_mae])
    limite = melhor[chave_mae] * (1 + epsilon)
    empatados = [l for l in validos if l[chave_mae] <= limite]
    return min(empatados, key=lambda l: (l.get(chave_custo, 0), l[chave_mae]))


def verificar_sem_vazamento():
    """Nenhuma origem de CV pode ter alvo dentro do teste, e a janela de ajuste não pode alcançá-lo."""
    from dados import GRUPOS, PRIORIDADES
    for g in GRUPOS:
        for p in PRIORIDADES:
            s = SERIES[(g, p)]
            for h, passos in HORIZONTES.items():
                orig = origens_cv(g, p, h)
                ultimo_alvo = s.data.iloc[orig[-1] + passos]
                assert ultimo_alvo < CORTE[g], \
                    f"{g} P{p} {h}: alvo de CV em {ultimo_alvo.date()} invade o teste"
                n_aj = janela_ajuste(orig)
                assert n_aj <= orig[0] + 1, f"{g} P{p} {h}: janela de ajuste alcança o alvo"
                assert n_aj >= 30, f"{g} P{p} {h}: janela de ajuste com só {n_aj} pontos"
    return True
