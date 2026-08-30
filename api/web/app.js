/* Tela de previsão — fetch e render, sem framework e sem passo de build.
   A regra que rege tudo aqui: nada de número solto. Todo valor previsto aparece com o selo da
   situação da data ao lado, e as ressalvas que a API devolve são exibidas, nunca filtradas. */

const $ = (id) => document.getElementById(id);
const NOME_GRUPO = {
  com_intervencao: ['com_intervencao', 'exigiu trabalho humano'],
  sem_intervencao: ['sem_intervencao', 'fechou sozinho no monitoramento'],
  total: ['total', 'modelo único sobre a prioridade inteira'],
};
const COR_GRUPO = { com_intervencao: '#2980b9', sem_intervencao: '#c0392b', total: '#2c3e50' };

let CATALOGO = null;
let grafico = null;

const num = (v, casas = 0) =>
  v === null || v === undefined ? '—'
    : Number(v).toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });

const classeSelo = (selo) => 'selo selo-' + selo.toLowerCase().replace(/ /g, '-');

async function pegar(rota, params) {
  const url = new URL(rota, location.origin);
  Object.entries(params || {}).forEach(([k, v]) => url.searchParams.set(k, v));
  const resposta = await fetch(url);
  const corpo = await resposta.json();
  if (!resposta.ok) throw new Error(corpo.detail || `erro ${resposta.status}`);
  return corpo;
}

// ================================================================================================
// Inicialização
// ================================================================================================

async function iniciar() {
  CATALOGO = await pegar('/api/catalogo');
  const { minima, maxima } = CATALOGO.datas;
  const campo = $('data');
  campo.min = minima;
  campo.max = maxima;
  campo.value = maxima;
  $('dica-data').textContent = `features disponíveis de ${br(minima)} a ${br(maxima)}`;

  $('consultar').onclick = consultar;
  $('exemplo').onclick = () => {
    $('data').value = '2025-12-15';
    $('prioridade').value = '3';
    $('horizonte').value = 'D+7';
    consultar();
  };
  consultar();
}

const br = (iso) => iso ? iso.split('-').reverse().join('/') : '—';

async function consultar() {
  const params = {
    data: $('data').value,
    prioridade: $('prioridade').value,
    horizonte: $('horizonte').value,
  };
  if (!params.data) return;

  $('titulo-previsao').textContent = `${br(params.data)} · P${params.prioridade} · ${params.horizonte}`;
  $('cards').innerHTML = '<p class="vazio">Consultando…</p>';

  try {
    const r = await pegar('/api/previsao', params);
    renderEntradas(r.entradas);
    renderCards(r);
    renderGrafico(r);
    renderAvisos(r.avisos);
  } catch (e) {
    $('cards').innerHTML = `<p class="erro">${e.message}</p>`;
    return;
  }

  pegar('/api/risco-ola', params).then(renderOla).catch(erroEm('ola'));
  pegar('/api/capacidade', params).then(renderCapacidade).catch(erroEm('capacidade'));

  const janela = CATALOGO.janelas.com_intervencao;
  pegar('/api/atipicos', {
    inicio: janela.corte, fim: CATALOGO.datas.maxima, prioridade: params.prioridade,
  }).then(renderAtipicos).catch(erroEm('atipicos'));
}

const erroEm = (id) => (e) => { $(id).innerHTML = `<p class="erro">${e.message}</p>`; };

// ================================================================================================
// Entradas
// ================================================================================================

function renderEntradas(entradas) {
  if (!entradas) { $('entradas').innerHTML = '<p class="vazio">Sem features nesta data.</p>'; return; }

  const s = entradas.serie, e = entradas.exogenas, c = entradas.calendario;
  const dias = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo'];
  const resumo = [
    ['abertos no dia', num(s.abertos)],
    ['soma 7 dias', num(s.soma7)],
    ['backlog', num(e.backlog)],
    ['incidentes por IC', num(e.inc_por_ic, 2)],
    ['ICs distintos', num(e.ics_distintos)],
    ['dia', dias[c.dia_semana] + (c.feriado ? ' · feriado' : c.dia_util ? ' · dia útil' : ' · não útil')],
  ];

  $('entradas').innerHTML = `
    <div class="resumo-linha">
      ${resumo.map(([k, v]) => `<div class="metrica"><span class="rotulo">${k}</span><span class="valor">${v}</span></div>`).join('')}
    </div>
    <details>
      <summary>Ver todas as features de entrada</summary>
      ${['serie', 'calendario', 'janela', 'exogenas', 'contexto'].map((bloco) => `
        <p style="margin:12px 0 2px;font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--texto-fraco);font-weight:700">${bloco}</p>
        <div class="grade-features">
          ${Object.entries(entradas[bloco] || {}).map(([k, v]) =>
            `<div class="par"><span>${k}</span><span>${v === null ? '—' : num(v, Number.isInteger(v) ? 0 : 3)}</span></div>`).join('')}
        </div>`).join('')}
      <p class="nota">As exógenas que este horizonte entrega ao modelo:
        ${Object.keys(entradas.exogenas_do_modelo).length
          ? Object.entries(entradas.exogenas_do_modelo).map(([k, v]) => `<b>${k}</b>=${num(v, 2)}`).join(' · ')
          : 'nenhuma — o vencedor deste corte é ARIMA puro, só o histórico da própria série.'}</p>
    </details>`;
}

// ================================================================================================
// Cards de previsão
// ================================================================================================

function renderCards(r) {
  const cards = CATALOGO.grupos.map((g) => cardDe(g, r.cards[g])).join('');
  $('cards').innerHTML = cards + (r.soma_dos_dois ? cardSoma(r.soma_dos_dois) : '');
}

function cardDe(grupo, c) {
  const [nome, descricao] = NOME_GRUPO[grupo];
  const sit = c.situacao;
  const cabecalho = `<div class="nome">${nome}<small>${descricao}</small></div>`;

  if (c.previsao === null) {
    return `<div class="card" style="border-left-color:${COR_GRUPO[grupo]}">
      ${cabecalho}
      <div class="numeros"><span class="vazio">${sit.explicacao}</span></div>
      <span class="${classeSelo(sit.selo)}" title="${sit.explicacao}">${sit.selo}</span></div>`;
  }

  const d = c.desempenho_no_teste;
  const marca = d.supera_ingenuo
    ? `<span class="marca ganha" title="MAE do modelo contra o piso ingênuo, no teste">✅ supera o ingênuo ${d.ganho_vs_ingenuo > 0 ? '+' : ''}${num(d.ganho_vs_ingenuo, 1)}%</span>`
    : `<span class="marca perde" title="Este modelo erra mais que a regra ingênua '${d.regra_ingenua}'">❌ perde do ingênuo ${num(d.ganho_vs_ingenuo, 1)}%</span>`;

  const metricas = [
    ['previsão', `${num(c.previsao)} <small>[${num(c.banda.inferior)}–${num(c.banda.superior)}]</small>`],
    ['real', c.real === null ? '<small>não existe ainda</small>' : num(c.real)],
    ['acurácia', c.acuracia_pct === null ? '—' : `${num(c.acuracia_pct, 1)}% <small>${c.erro > 0 ? '+' : ''}${num(c.erro)}</small>`],
    ['ingênuo', `${num(c.ingenuo.valor)} <small>${c.ingenuo.regra}</small>`],
  ];

  return `<div class="card" style="border-left-color:${COR_GRUPO[grupo]}">
    ${cabecalho}
    <div class="numeros">
      ${metricas.map(([k, v]) => `<div class="metrica"><span class="rotulo">${k}</span><span class="valor">${v}</span></div>`).join('')}
    </div>
    <div style="text-align:right">
      <span class="${classeSelo(sit.selo)}" title="${sit.explicacao}">${sit.selo}</span>
      <div style="margin-top:6px">${marca}</div>
      <div style="font-size:11px;color:var(--texto-fraco);margin-top:2px">${c.modelo}</div>
    </div></div>`;
}

function cardSoma(s) {
  const vantagem = s.vantagem_da_separacao_pct === null ? ''
    : `<div class="metrica"><span class="rotulo">vs. modelo único</span><span class="valor">${s.vantagem_da_separacao_pct > 0 ? '+' : ''}${num(s.vantagem_da_separacao_pct, 1)}%</span></div>`;
  return `<div class="card soma">
    <div class="nome">soma dos 2 modelos<small>com_intervencao + sem_intervencao</small></div>
    <div class="numeros">
      <div class="metrica"><span class="rotulo">previsão</span><span class="valor">${num(s.previsao)}</span></div>
      <div class="metrica"><span class="rotulo">real</span><span class="valor">${s.real === null ? '—' : num(s.real)}</span></div>
      <div class="metrica"><span class="rotulo">acurácia</span><span class="valor">${s.acuracia_pct === null ? '—' : num(s.acuracia_pct, 1) + '%'}</span></div>
      ${vantagem}
    </div>
    <div style="font-size:11px;color:var(--texto-fraco);max-width:190px;text-align:right">${s.nota}</div></div>`;
}

// ================================================================================================
// Gráfico
// ================================================================================================

function renderGrafico(r) {
  const series = r.grafico.series;
  const rotulos = (series.total || series.com_intervencao).historico.map((p) => p.data);
  const alvo = Object.values(series)[0].previsao?.data;
  if (alvo && !rotulos.includes(alvo)) rotulos.push(alvo);

  const conjuntos = [];
  for (const [grupo, s] of Object.entries(series)) {
    const mapa = Object.fromEntries(s.historico.map((p) => [p.data, p.valor]));
    conjuntos.push({
      label: grupo, data: rotulos.map((d) => mapa[d] ?? null),
      borderColor: COR_GRUPO[grupo], backgroundColor: COR_GRUPO[grupo],
      borderWidth: 1.6, pointRadius: 0, tension: 0.15, spanGaps: false,
    });
    if (s.previsao) {
      const ponto = rotulos.map((d) => (d === s.previsao.data ? s.previsao.valor : null));
      conjuntos.push({
        label: `${grupo} · previsto`, data: ponto,
        borderColor: COR_GRUPO[grupo], backgroundColor: '#fff',
        pointRadius: 6, pointStyle: 'circle', pointBorderWidth: 2.5, showLine: false,
      });
      if (s.previsao.real !== null && s.previsao.real !== undefined) {
        conjuntos.push({
          label: `${grupo} · real`, data: rotulos.map((d) => (d === s.previsao.data ? s.previsao.real : null)),
          borderColor: COR_GRUPO[grupo], backgroundColor: COR_GRUPO[grupo],
          pointRadius: 5, pointStyle: 'rectRot', showLine: false,
        });
      }
    }
  }

  if (grafico) grafico.destroy();
  grafico = new Chart($('grafico'), {
    type: 'line',
    data: { labels: rotulos.map(br), datasets: conjuntos },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { boxWidth: 12, font: { size: 11 } } },
        title: { display: true, align: 'start', font: { size: 11 },
                 text: `série ${r.grafico.coluna} — círculo vazado = previsto, losango = real` },
      },
      scales: { x: { ticks: { maxTicksLimit: 12, font: { size: 10 } } },
                y: { beginAtZero: true, ticks: { font: { size: 10 } } } },
    },
  });
}

// ================================================================================================
// Avisos
// ================================================================================================

function renderAvisos(avisos) {
  $('bloco-avisos').hidden = !avisos || !avisos.length;
  $('avisos').innerHTML = (avisos || []).map((a) =>
    `<div class="aviso ${a.nivel}"><b>${a.grupo || a.nivel}</b>${a.texto}</div>`).join('');
}

// ================================================================================================
// Painel de OLA
// ================================================================================================

function renderOla(r) {
  const regras = Object.entries(r.regras).map(([nome, g]) => blocoRegra(nome, g)).join('');
  $('ola').innerHTML = `
    <p style="font-size:12.5px;color:var(--texto-fraco);margin:0 0 12px">
      Acumulado anual da prioridade inteira em ${br(r.data)}, projetado até ${br(r.fim_da_projecao)}
      (${r.dias_projetados} dias).</p>
    ${regras}
    ${(r.avisos || []).map((a) => `<div class="aviso ${a.nivel}"><b>${a.nivel}</b>${a.texto}</div>`).join('')}
    <p class="nota">${r.nota_de_metodo}</p>`;
}

function blocoRegra(nome, g) {
  const titulo = nome === 'duracao' ? 'Regra de duração (KPI violado)' : 'Regra de volume (fechamentos)';
  if (!g.tem_meta) {
    return `<div style="margin-bottom:16px"><b>${titulo}</b>
      <p class="vazio">Sem meta definida para esta prioridade. Acumulado hoje: ${num(g.acumulado_hoje)} ${g.unidade}.</p></div>`;
  }

  const c = g.cenario_taxa_recente;
  const linhas = [
    ['atingimento hoje', `${num(g.atingimento_hoje_pct)}%`],
    ['acumulado', `${num(g.acumulado_hoje)} ${g.unidade}`],
    ['próximo corte', g.proximo_corte === null ? 'não há' : num(g.proximo_corte)],
    ['orçamento restante', g.orcamento_restante === null ? '—' : num(g.orcamento_restante)],
  ];

  const cenarios = `
    <table><thead><tr><th>cenário</th><th class="num">projeção</th><th class="num">risco de cair</th><th>cruza o corte</th></tr></thead>
    <tbody>
      <tr><td>taxa de 28 dias</td><td class="num">${num(g.projecao.atingimento_esperado_pct)}%</td>
          <td class="num">${(g.probabilidade_de_piorar * 100).toFixed(0)}%</td>
          <td>${g.data_provavel_de_cruzamento ? br(g.data_provavel_de_cruzamento.data) : '—'}</td></tr>
      <tr><td>taxa de 7 dias <small>(${c.tendencia.leitura.split('—')[0].trim()})</small></td>
          <td class="num">${num(c.atingimento_esperado_pct)}%</td>
          <td class="num"><b>${(c.probabilidade_de_piorar * 100).toFixed(0)}%</b></td>
          <td>${c.data_provavel_de_cruzamento ? br(c.data_provavel_de_cruzamento.data) : '—'}</td></tr>
    </tbody></table>`;

  return `<div style="margin-bottom:18px">
    <b>${titulo}</b>${g.faixa_estourada ? ' <span class="marca perde">faixa estourada</span>' : ''}
    <div class="resumo-linha" style="margin-top:8px">
      ${linhas.map(([k, v]) => `<div class="metrica"><span class="rotulo">${k}</span><span class="valor">${v}</span></div>`).join('')}
    </div>
    ${g.faixa_estourada ? '' : cenarios}
    ${g.faixa_estourada ? '' : `<p class="nota">Distribuição do fim do período: ${g.distribuicao_de_faixas
        .map((d) => `${num(d.atingimento_pct)}% (${(d.probabilidade * 100).toFixed(0)}%)`).join(' · ')}</p>`}
  </div>`;
}

// ================================================================================================
// Painel de capacidade
// ================================================================================================

function renderCapacidade(r) {
  if (!r.dimensionamento) {
    $('capacidade').innerHTML = `<p class="vazio">${r.avisos.map((a) => a.texto).join(' ')}</p>`;
    return;
  }
  const d = r.dimensionamento, e = r.entrada, p = r.parametros;
  const metricas = [
    ['analistas por dia', num(d.analistas_por_dia, 1)],
    ['no topo da banda', num(d.analistas_por_dia_pior_caso, 1)],
    ['horas por dia', num(d.horas_por_dia, 1)],
    ['incidentes previstos', num(e.incidentes_previstos)],
  ];

  $('capacidade').innerHTML = `
    <p style="font-size:12.5px;color:var(--texto-fraco);margin:0 0 12px">
      Só a fatia <b>com_intervencao</b> — o que fecha sozinho no monitoramento não consome analista.</p>
    <div class="resumo-linha">
      ${metricas.map(([k, v]) => `<div class="metrica"><span class="rotulo">${k}</span><span class="valor">${v}</span></div>`).join('')}
    </div>
    <table><thead><tr><th>turno</th><th class="num">share</th><th class="num">analistas</th><th class="num">horas</th></tr></thead>
      <tbody>${r.por_turno.map((t) => `<tr><td>${t.turno}</td><td class="num">${(t.share * 100).toFixed(1)}%</td>
        <td class="num">${num(t.analistas, 1)}</td><td class="num">${num(t.horas, 1)}</td></tr>`).join('')}</tbody></table>
    <p class="nota">${num(e.incidentes_previstos)} incidentes × ${num(e.duracao_mediana_h, 2)} h de duração mediana
      × fator de esforço ${p.fator_esforco} ÷ (${p.jornada_h} h × ${(p.ocupacao * 100).toFixed(0)}% de ocupação)
      ÷ ${e.dias_cobertos} dia(s).</p>
    ${r.avisos.map((a) => `<div class="aviso ${a.nivel}"><b>${a.nivel}</b>${a.texto}</div>`).join('')}`;
}

// ================================================================================================
// Painel de dias atípicos
// ================================================================================================

function renderAtipicos(r) {
  const s = r.resumo;
  const linhas = r.atipicos.length
    ? r.atipicos.map((d) => `<tr>
        <td>${br(d.data)}</td>
        <td><span class="${classeSelo(d.selo)}">${d.selo}</span></td>
        <td class="num">${num(d.previsto)}</td>
        <td class="num"><small>${num(d.banda.inferior)}–${num(d.banda.superior)}</small></td>
        <td class="num"><b>${num(d.real)}</b></td>
        <td class="num">${d.desvio_pct > 0 ? '+' : ''}${num(d.desvio_pct, 1)}%</td>
        <td>${d.concentracao ? d.concentracao.leitura : '—'}</td>
        <td class="num">${d.concentracao && d.concentracao.razao !== null
            ? `${num(d.concentracao.inc_por_ic, 2)} <small>vs ${num(d.concentracao.mediana_90d, 2)}</small>` : '—'}</td>
      </tr>`).join('')
    : '<tr><td colspan="8" class="vazio">Nenhum dia fora da banda no intervalo.</td></tr>';

  $('atipicos').innerHTML = `
    <p style="font-size:12.5px;color:var(--texto-fraco);margin:0 0 12px">
      Grupo <b>${r.grupo}</b>, P${r.prioridade}, de ${br(r.intervalo.inicio)} a ${br(r.intervalo.fim)},
      banda de ${r.confianca_da_banda_pct}%. ${s.leitura}
      ${s.com_marca_de_sistemico} com marca de evento sistêmico.</p>
    <div class="rolagem"><table>
      <thead><tr><th>data</th><th>situação</th><th class="num">previsto</th><th class="num">banda</th>
        <th class="num">real</th><th class="num">fora por</th><th>leitura</th><th class="num">inc. por IC</th></tr></thead>
      <tbody>${linhas}</tbody></table></div>
    ${r.avisos.map((a) => `<div class="aviso ${a.nivel}"><b>${a.nivel}</b>${a.texto}</div>`).join('')}`;
}

iniciar();
