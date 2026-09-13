/* Painel principal — sem framework e sem passo de build.
   Uma chamada por data traz as 3 prioridades; o filtro de prioridade só redesenha. Com e sem
   intervenção vêm empilhados: a pilha prevista é a soma dos dois modelos.
   Cores e fonte vêm dos tokens de marca.css — nenhum hex aqui. */

const $ = (id) => document.getElementById(id);

const REGRAS = { duracao: 'Duração · KPI violado', volume: 'Volume · fechamentos' };
const PASSOS = 7;

const estado = { origem: null, prioridade: '3' };
const cache = {};
const graficos = {};

// ================================================================================================
// Utilidades
// ================================================================================================

const token = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
const num = (v, casas = 0) => (v === null || v === undefined ? '—'
  : Number(v).toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas }));
const pct = (p) => (p === null || p === undefined ? '—' : `${Math.round(p * 100)}%`);
const dm = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '—');
const dma = (iso) => (iso ? iso.split('-').reverse().join('/') : '—');
const somaDias = (iso, n) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const wash = (hex, alfa) => {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alfa})`;
};
const chave = (grupo) => `<span class="chave" style="background:var(--grupo-${grupo})"></span>`;
const soma = (par) => (par.com === null || par.sem === null ? null : par.com + par.sem);
const nomePrioridade = () => (estado.prioridade === 'todas' ? 'todas as prioridades' : `P${estado.prioridade}`);
// A URL acompanha data e prioridade: copiar o endereço dá o link exato do que está na tela.
const guardarNaUrl = () => history.replaceState(null, '',
  `?data=${estado.origem}&prioridade=${estado.prioridade}`);

async function carregar(origem) {
  if (!cache[origem]) {
    const resposta = await fetch(`/api/painel?origem=${origem}`);
    const corpo = await resposta.json();
    if (!resposta.ok) throw new Error(corpo.detail || `erro ${resposta.status}`);
    cache[origem] = corpo;
  }
  return cache[origem];
}

// ================================================================================================
// Filtros
// ================================================================================================

function iniciar() {
  // `?data=AAAA-MM-DD&prioridade=3|todas` abre o painel direto numa data e numa prioridade —
  // link de demonstração.
  const pedido = new URLSearchParams(location.search);
  if (pedido.get('data')) $('data').value = pedido.get('data');
  if (['2', '3', '4', 'todas'].includes(pedido.get('prioridade'))) estado.prioridade = pedido.get('prioridade');
  estado.origem = $('data').value;
  $('data').addEventListener('change', () => irPara($('data').value));
  $('dia-anterior').addEventListener('click', () => irPara(somaDias(estado.origem, -1)));
  $('dia-seguinte').addEventListener('click', () => irPara(somaDias(estado.origem, 1)));
  $('f-prioridade').addEventListener('click', (e) => {
    const botao = e.target.closest('button[data-valor]');
    if (!botao || estado.prioridade === botao.dataset.valor) return;
    estado.prioridade = botao.dataset.valor;
    guardarNaUrl();
    atualizar();
  });
  coresDoTema();
  // Troca de tema: os gráficos guardam as cores da criação, então redesenham (dado em cache).
  document.addEventListener('tema', () => { coresDoTema(); atualizar(); });
  atualizar();
}

function coresDoTema() {
  Chart.defaults.font.family = token('--marca-fonte');
  Chart.defaults.color = token('--marca-tinta-3');
}

function irPara(iso) {
  const campo = $('data');
  if (!iso || iso < campo.min || iso > campo.max) return;
  estado.origem = iso;
  campo.value = iso;
  guardarNaUrl();
  atualizar();
}

async function atualizar() {
  $('f-prioridade').querySelectorAll('button').forEach((b) =>
    b.setAttribute('aria-pressed', String(b.dataset.valor === estado.prioridade)));
  $('dia-anterior').disabled = estado.origem <= $('data').min;
  $('dia-seguinte').disabled = estado.origem >= $('data').max;
  document.body.classList.add('carregando');
  try {
    const dados = await carregar(estado.origem);
    $('data').min = dados.intervalo.inicio;
    $('data').max = dados.intervalo.fim;
    const b = dados.prioridades[estado.prioridade];
    renderSituacao(dados.situacao);
    renderNumeros(b);
    renderD1(b);
    renderD7(b);
    renderKpis(dados.kpis);
    $('erro').hidden = true;
  } catch (e) {
    $('erro').textContent = e.message;
    $('erro').hidden = false;
  } finally {
    document.body.classList.remove('carregando');
  }
}

function renderSituacao(s) {
  const detalhe = s.detalhe.map((d) => `${d.grupo} ${d.horizonte}: ${d.selo}`).join('\n');
  $('situacao').innerHTML = `<b>${s.chave}</b>${s.texto}`;
  $('situacao').title = detalhe;
}

// ================================================================================================
// Números principais
// ================================================================================================

function renderNumeros(b) {
  const ultima = b.semanal[b.semanal.length - 1];
  const realizadoSemana = soma(ultima);
  const variacao = realizadoSemana ? b.d7.previsto / realizadoSemana - 1 : null;
  const tendencia = variacao === null ? ''
    : ` · ${variacao >= 0 ? '▲' : '▼'} ${num(Math.abs(variacao * 100))}% vs. última semana`;
  const partes = (x) => `${chave('com')}com ${num(x.com)} · ${chave('sem')}sem ${num(x.sem)}`;
  // Realizado do período previsto, quando já existe — separado por tipo, como o previsto.
  const realizado = (x) => (x.real === null ? ''
    : `<div class="sub">realizado: <b>${num(x.real)}</b> · ${partes({ com: x.com.real, sem: x.sem.real })}</div>`);

  $('numeros').innerHTML = `
    <div class="tile previsto">
      <div class="rotulo">Amanhã · ${dma(b.d1.inicio)}</div>
      <div class="valor">${num(b.d1.previsto)}</div>
      <div class="sub">${partes({ com: b.d1.com.previsao, sem: b.d1.sem.previsao })}</div>
      ${realizado(b.d1)}
    </div>
    <div class="tile previsto">
      <div class="rotulo">Próximos 7 dias · ${dm(b.d7.inicio)} a ${dm(b.d7.fim)}</div>
      <div class="valor">${num(b.d7.previsto)}</div>
      <div class="sub">${partes({ com: b.d7.com.previsao, sem: b.d7.sem.previsao })}${tendencia}</div>
      ${realizado(b.d7)}
    </div>
    <div class="tile">
      <div class="rotulo">Última semana · ${dm(ultima.inicio)} a ${dm(ultima.fim)}</div>
      <div class="valor">${num(realizadoSemana)}</div>
      <div class="sub">${partes(ultima)} · realizado</div>
    </div>`;
}

// ================================================================================================
// Gráficos — barras empilhadas, com intervenção na base (é o que consome analista)
// ================================================================================================

// Linha fina separando o realizado do previsto, com os dois rótulos.
const divisor = {
  id: 'divisor',
  afterDatasetsDraw(chart, _args, opcoes) {
    const x = chart.scales.x;
    const { top, bottom } = chart.chartArea;
    const meio = (x.getPixelForValue(opcoes.indice - 1) + x.getPixelForValue(opcoes.indice)) / 2;
    const c = chart.ctx;
    c.save();
    c.strokeStyle = token('--eixo');
    c.lineWidth = 1;
    c.beginPath(); c.moveTo(meio, top); c.lineTo(meio, bottom); c.stroke();
    c.fillStyle = token('--marca-tinta-3');
    c.font = `11px ${token('--marca-fonte')}`;
    c.textAlign = 'right'; c.fillText('realizado', meio - 6, top + 12);
    // Em tela estreita a faixa prevista é uma barra só: o rótulo não cabe e não é desenhado.
    if (meio + 6 + c.measureText('previsto').width <= chart.chartArea.right) {
      c.textAlign = 'left'; c.fillText('previsto', meio + 6, top + 12);
    }
    c.restore();
  },
};

/* `realizado`: [{com, sem}] do passado; `previsao`: o bloco d1/d7 da API (vira a última barra). */
function graficoPilha(id, rotulos, realizado, previsao) {
  const n = rotulos.length;
  const vazio = () => Array(n).fill(null);
  const corCom = token('--grupo-com');
  const corSem = token('--grupo-sem');
  const superficie = token('--marca-superficie');

  const serie = (grupo, fonte) => {
    const v = vazio();
    if (fonte === 'real') realizado.forEach((p, k) => { v[k] = p[grupo]; });
    else v[n - 1] = previsao[grupo].previsao;
    return v;
  };
  const marcador = vazio();
  marcador[n - 1] = previsao.real;

  // 2px de superfície no topo de cada segmento: o respiro entre as camadas da pilha.
  const barra = (label, data, cor, topo) => ({
    type: 'bar', label, data, backgroundColor: cor, stack: 'pilha', maxBarThickness: 28,
    borderColor: superficie, borderWidth: { top: 2 },
    borderRadius: topo ? { topLeft: 4, topRight: 4 } : 0,
  });

  const conjuntos = [
    barra('Com intervenção', serie('com', 'real'), corCom, false),
    barra('Sem intervenção', serie('sem', 'real'), corSem, true),
    barra('Com · previsto', serie('com', 'prev'), wash(corCom, 0.38), false),
    barra('Sem · previsto', serie('sem', 'prev'), wash(corSem, 0.38), true),
    { type: 'line', label: 'Realizado no período previsto', data: marcador, stack: 'marcador',
      showLine: false, pointStyle: 'rectRot', pointRadius: 7, pointHoverRadius: 8,
      backgroundColor: token('--marca-tinta'), borderColor: token('--marca-tinta'),
      pointBorderColor: superficie, pointBorderWidth: 2 },
  ];

  const faixa = (grupo) => previsao[grupo].banda;
  const rotulo = (ctx) => {
    const v = ctx.raw;
    if (ctx.dataset.stack === 'marcador') {
      return ` realizado: ${num(v)} (com ${num(previsao.com.real)} · sem ${num(previsao.sem.real)})`;
    }
    if (ctx.dataset.label === 'Com · previsto' || ctx.dataset.label === 'Sem · previsto') {
      const f = faixa(ctx.dataset.label.startsWith('Com') ? 'com' : 'sem');
      // Visão agregada: a faixa de uma soma não é a soma das faixas — sem faixa, sem inventar.
      if (!f) return ` ${ctx.dataset.label}: ${num(v)} (soma das 3 prioridades)`;
      return ` ${ctx.dataset.label}: ${num(v)} (faixa de ${f.confianca_pct}%: ${num(f.inferior)}–${num(f.superior)})`;
    }
    return ` ${ctx.dataset.label}: ${num(v)}`;
  };
  const rodape = (itens) => {
    const total = itens.filter((i) => i.dataset.stack === 'pilha')
      .reduce((acc, i) => acc + (i.raw || 0), 0);
    return `total: ${num(total)}`;
  };

  if (graficos[id]) graficos[id].destroy();
  graficos[id] = new Chart($(id), {
    data: { labels: rotulos, datasets: conjuntos },
    plugins: [divisor],
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        divisor: { indice: n - 1 },
        legend: {
          position: 'bottom',
          labels: { boxWidth: 12, boxHeight: 12, color: token('--marca-tinta-2'),
                    filter: (item, dados) => dados.datasets[item.datasetIndex].data.some((v) => v !== null) },
        },
        tooltip: { filter: (ctx) => ctx.raw !== null, callbacks: { label: rotulo, footer: rodape } },
      },
      scales: {
        x: { stacked: true, grid: { display: false }, border: { color: token('--eixo') } },
        y: { stacked: true, beginAtZero: true, grid: { color: token('--grade') }, border: { display: false },
             ticks: { callback: (v) => num(v), maxTicksLimit: 6 } },
      },
    },
  });
}

function tabela(id, linhas) {
  $(id).innerHTML = `<table>
    <thead><tr><th>período</th><th class="num">com</th><th class="num">sem</th><th class="num">total</th><th></th></tr></thead>
    <tbody>${linhas.map(([rotulo, com, sem, tipo]) => `<tr><td>${rotulo}</td><td class="num">${num(com)}</td>
      <td class="num">${num(sem)}</td><td class="num">${num(com === null || sem === null ? null : com + sem)}</td>
      <td>${tipo}</td></tr>`).join('')}</tbody></table>`;
}

function renderD1(b) {
  const rotulos = [...b.diario.map((p) => dm(p.data)), dm(b.d1.inicio)];
  graficoPilha('grafico-d1', rotulos, b.diario, b.d1);
  $('sub-d1').textContent = `Incidentes abertos por dia, ${nomePrioridade()}: os últimos `
    + `${b.diario.length} dias e a previsão de ${dma(b.d1.inicio)}.`;
  tabela('tabela-d1', [
    ...b.diario.map((p) => [dma(p.data), p.com, p.sem, 'realizado']),
    [`${dma(b.d1.inicio)} (D+1)`, b.d1.com.previsao, b.d1.sem.previsao, 'previsto'],
    ...linhaRealizada(`${dma(b.d1.inicio)} (D+1)`, b.d1),
  ]);
}

function renderD7(b) {
  const semana = (i, f) => `${dm(i)}–${dm(f)}`;
  const rotulos = [...b.semanal.map((s) => semana(s.inicio, s.fim)), semana(b.d7.inicio, b.d7.fim)];
  graficoPilha('grafico-d7', rotulos, b.semanal, b.d7);
  $('sub-d7').textContent = `Incidentes abertos por semana, ${nomePrioridade()}: as últimas `
    + `${b.semanal.length} semanas e o acumulado previsto de ${dm(b.d7.inicio)} a ${dm(b.d7.fim)}.`;
  tabela('tabela-d7', [
    ...b.semanal.map((s) => [semana(s.inicio, s.fim), s.com, s.sem, 'realizado']),
    [`${semana(b.d7.inicio, b.d7.fim)} (D+7)`, b.d7.com.previsao, b.d7.sem.previsao, 'previsto'],
    ...linhaRealizada(`${semana(b.d7.inicio, b.d7.fim)} (D+7)`, b.d7),
  ]);
}

// Linha do realizado no período previsto, por tipo — só quando o real já existe.
const linhaRealizada = (rotulo, p) => (p.real === null ? []
  : [[rotulo, p.com.real, p.sem.real, 'realizado']]);

// ================================================================================================
// KPIs de OLA — o resto do ano corrente e, na virada, o ano novo no ritmo atual
// ================================================================================================

const nivel = (p) => (p >= 0.5 ? ['alto', 'risco alto'] : p >= 0.2 ? ['moderado', 'risco moderado'] : ['baixo', 'risco baixo']);
const status = (p) => { const [classe, texto] = nivel(p); return `<span class="status ${classe}">${texto}</span>`; };

// Rosca do atingimento. O anel inteiro é a escala (0 a 150%); o arco é o atingimento do dia, na
// cor da faixa; o tracinho marca a meta de 100%. O trecho que pulsa é o que se perde se o
// acumulado cruzar o próximo corte até 31/12 — a intensidade do pulso acompanha a chance.
const COR_FAIXA = { 150: '--ola-150', 125: '--ola-125', 100: '--ola-100', 75: '--ola-75', 50: '--ola-50', 0: '--ola-0' };

function rosca(r) {
  const c = r.ano_corrente;
  const topo = r.escala[0];
  const atual = c.atingimento_hoje_pct;
  const i = r.escala.indexOf(atual);
  const abaixo = i >= 0 && i < r.escala.length - 1 ? r.escala[i + 1] : null;
  const chance = c.fechado || c.faixa_estourada ? 0 : c.probabilidade_de_piorar;

  const R = 36;
  const C = 2 * Math.PI * R;
  const arco = (de, ate) => `stroke-dasharray="${((ate - de) / topo) * C} ${C}" stroke-dashoffset="${(-de / topo) * C}"`;
  const angulo = (2 * Math.PI * 100) / topo;
  const ponto = (raio) => `${45 + raio * Math.cos(angulo)} ${45 + raio * Math.sin(angulo)}`;
  const [x1, y1] = ponto(R - 7).split(' ');
  const [x2, y2] = ponto(R + 7).split(' ');

  const emRisco = abaixo !== null && chance >= 0.01;
  const quando = c.fechado ? 'final' : 'hoje';
  const descricao = `Atingimento ${quando}: ${num(atual)}%`
    + (emRisco ? `; ${pct(chance)} de chance de cair para ${num(abaixo)}% até 31/12` : '');

  return `<svg class="rosca" viewBox="0 0 90 90" role="img" aria-label="${descricao}">
    <title>${descricao}</title>
    <g transform="rotate(-90 45 45)">
      <circle class="trilho" r="${R}" cx="45" cy="45"/>
      ${atual > 0 ? `<circle r="${R}" cx="45" cy="45" ${arco(0, atual)} style="stroke:var(${COR_FAIXA[atual]})"/>` : ''}
      ${emRisco ? `<circle class="em-risco" r="${R}" cx="45" cy="45" ${arco(abaixo, atual)}
                   style="--intensidade:${(0.35 + 0.65 * chance).toFixed(2)}"/>` : ''}
      <line class="meta" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>
    </g>
    <text x="45" y="49" class="rosca-valor">${num(atual)}%</text>
    <text x="45" y="62" class="rosca-rotulo">${quando}</text>
  </svg>`;
}

function linhaCorrente(r) {
  const c = r.ano_corrente;
  if (c.fechado) {
    return `<div class="kpi-linha">
      <div><span class="rotulo">${c.ano} fechou na faixa ao lado</span>
           <span class="sub">${num(c.acumulado_hoje)} ${r.unidade} no ano</span></div></div>`;
  }
  if (c.faixa_estourada) {
    return `<div class="kpi-linha">
      <div><span class="rotulo">${c.ano} já está em 0%</span>
           <span class="sub">o acumulado (${num(c.acumulado_hoje)}) passou o último corte; não há faixa para onde cair</span></div></div>`;
  }
  const cruza = c.data_provavel_de_cruzamento;
  const quando = cruza && cruza.dentro_da_projecao
    ? `cruza por volta de ${dma(cruza.data)}` : `não cruza até 31/12 neste ritmo`;
  return `<div class="kpi-linha">
    <div><span class="rotulo">até 31/12/${c.ano} · chance de cair dos ${num(c.atingimento_hoje_pct)}%</span>
         <span class="sub">acumulado ${num(c.acumulado_hoje)} de ${num(c.proximo_corte)} ${r.unidade} · ${quando}</span>
         ${status(c.probabilidade_de_piorar)}</div>
    <span class="valor">${pct(c.probabilidade_de_piorar)}</span></div>`;
}

function linhaAnoNovo(r) {
  const a = r.ano_novo;
  if (!a) return '';
  const cruza = a.data_provavel_de_cruzamento;
  const quando = cruza && cruza.dentro_da_projecao
    ? `cruza ${num(a.primeiro_corte)} ${r.unidade} por volta de ${dma(cruza.data)}`
    : `não cruza ${num(a.primeiro_corte)} ${r.unidade} em ${a.ano} neste ritmo`;
  return `<div class="kpi-linha">
    <div><span class="rotulo">${a.ano} no ritmo atual · chance de sair dos ${num(a.atingimento_inicial_pct)}%</span>
         <span class="sub">${quando}</span>${status(a.probabilidade_de_quebra)}</div>
    <span class="valor">${pct(a.probabilidade_de_quebra)}</span></div>`;
}

function renderKpis(kpis) {
  // As faixas de OLA são calibradas por prioridade: na visão agregada não existe acumulado que se
  // some. Cada prioridade aparece com as suas roscas, uma embaixo da outra.
  const todas = estado.prioridade === 'todas';
  const lista = todas ? Object.keys(kpis) : [estado.prioridade];
  const virada = lista.some((p) => Object.values(kpis[p].regras || {}).some((r) => r.ano_novo));
  $('sub-kpis').textContent = (todas
    ? 'Cada prioridade com o seu acumulado anual: as faixas de OLA são por prioridade e não se somam. '
    : `P${estado.prioridade} · acumulado anual da prioridade inteira. `)
    + `A partir de ${dma(estado.origem)}.${virada ? ' A semana prevista atravessa a virada: o ano novo começa do zero.' : ''}`;

  const blocos = lista.map((p) => (todas ? `<div class="kpi-prioridade">P${p}</div>` : '')
    + kpisDaPrioridade(kpis[p], p));
  const temMeta = lista.some((p) => kpis[p].tem_meta);
  const legenda = 'O anel vai de 0 a 150%, e o tracinho é a meta de 100%. O trecho vermelho que pulsa '
    + 'é a faixa que se perde se o acumulado cruzar o próximo corte até 31/12: quanto mais forte, mais provável.';
  const metodo = lista.map((p) => (kpis[p].avisos || []).find((a) => a.texto.startsWith('A leitura de')))
    .find(Boolean);
  $('kpis').innerHTML = blocos.join('') + (temMeta ? `<p class="nota">${legenda}</p>` : '')
    + (metodo ? `<p class="nota">${metodo.texto}</p>` : '');
}

function kpisDaPrioridade(k, p) {
  if (!k.tem_meta) {
    return `<p class="vazio">P${p} não tem meta de OLA definida, nem de duração nem de volume. É uma
      pendência aberta com a área, e o painel não inventa número.</p>`;
  }

  return Object.entries(REGRAS).map(([nome, titulo]) => {
    const r = k.regras[nome];
    if (!r.tem_meta) return `<div class="kpi"><h3>${titulo}</h3><p class="vazio">Sem meta definida.</p></div>`;
    return `<div class="kpi">
      <h3>${titulo}${r.ano_corrente.faixa_estourada ? '<span class="etiqueta">faixa estourada</span>' : ''}</h3>
      <div class="kpi-corpo">
        ${rosca(r)}
        <div class="kpi-linhas">${linhaCorrente(r)}${linhaAnoNovo(r)}</div>
      </div>
    </div>`;
  }).join('');
}

iniciar();
