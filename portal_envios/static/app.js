/* Portal de envios D55: tela. Toda regra fica no servidor (app.py), que usa a lógica do painel atual. */
(() => {
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const reduz = matchMedia('(prefers-reduced-motion: reduce)');
const usd = (v) => 'US$ ' + Number(v || 0).toFixed(2).replace('.', ',');
const digitos = (s) => String(s ?? '').replace(/\D/g, '');
const fmtBR = (s) => (s && s.length >= 10 ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : s);
const LINK_USPS = 'https://tools.usps.com/go/TrackConfirmAction?tLabels=';

/* ============ COMUNICAÇÃO COM O SERVIDOR ============ */
class Erro extends Error { constructor(msg, status, corpo) { super(msg); this.status = status; this.corpo = corpo; } }
async function api(caminho, { metodo = 'GET', json, form, bruto = false } = {}) {
  const opcoes = { method: metodo, headers: {}, credentials: 'same-origin' };
  if (metodo !== 'GET') opcoes.headers['X-Portal'] = '1';
  if (json !== undefined) { opcoes.headers['Content-Type'] = 'application/json'; opcoes.body = JSON.stringify(json); }
  if (form) opcoes.body = form;
  let r;
  try { r = await fetch(caminho, opcoes); } catch { throw new Erro('Sem conexão com o servidor. Tente de novo.', 0); }
  if (r.status === 401 && caminho !== '/api/login') { mostrarLogin('Sua sessão expirou. Entre de novo.'); throw new Erro('Sessão expirada.', 401); }
  if (bruto && r.ok) return r;
  let corpo = null;
  try { corpo = await r.json(); } catch { /* resposta sem JSON */ }
  if (!r.ok) throw new Erro((corpo && corpo.detail) || `Erro ${r.status} no servidor.`, r.status, corpo);
  return corpo;
}
const silencioso = (e) => e.status === 401; // sessão expirada já leva para o login

/* ============ UTILITÁRIOS DE TELA ============ */
function toast(msg, tipo = 'info', ms = 5000) {
  const icones = { info: 'info', ok: 'check_circle', aviso: 'warning', erro: 'error' };
  const el = document.createElement('div');
  el.className = `toast ${tipo}`;
  el.innerHTML = `<i class="material-icons" aria-hidden="true">${icones[tipo]}</i><div>${msg}</div>`;
  $('#toasts').append(el);
  setTimeout(() => { el.classList.add('sai'); setTimeout(() => el.remove(), 320); }, ms);
}
async function ocupado(btn, texto, fn) {
  const antes = btn.innerHTML; btn.disabled = true;
  btn.innerHTML = `<span class="gira" aria-hidden="true"></span>${esc(texto)}`;
  try { return await fn(); } finally { btn.innerHTML = antes; btn.disabled = false; }
}
function cantos(raiz = document) {
  $$('.caixa', raiz).forEach((c) => {
    if (c.querySelector(':scope > .canto')) return;
    c.insertAdjacentHTML('afterbegin', '<span class="canto tl" aria-hidden="true"></span><span class="canto br" aria-hidden="true"></span>');
  });
}
function embaralhar(el) {
  if (!el || reduz.matches || el._anim) return;
  const final = el.dataset.t, t0 = performance.now(), dur = 420;
  el.style.minWidth = el.offsetWidth + 'px';
  const passo = (t) => {
    const p = Math.min(1, (t - t0) / dur), fixos = Math.floor(p * final.length);
    el.textContent = final.slice(0, fixos) + [...final.slice(fixos)].map((c) => (c === ' ' ? ' ' : Math.random() < 0.5 ? '0' : '1')).join('');
    if (p < 1) { el._anim = requestAnimationFrame(passo); return; }
    el.textContent = final; el.style.minWidth = ''; el._anim = 0;
  };
  el._anim = requestAnimationFrame(passo);
}
function seg(container, nome, opcoes, atual, aoMudar) {
  container.innerHTML = opcoes.map((o) => `<label><input type="radio" name="${nome}" value="${esc(o)}"${o === atual ? ' checked' : ''}><span>${esc(o)}</span></label>`).join('');
  container.onchange = (e) => aoMudar(e.target.value);
}
function arquivo(drop, input, txtEl) {
  const padrao = txtEl.innerHTML;
  const atualizar = () => {
    const n = input.files.length;
    drop.classList.toggle('tem', n > 0);
    txtEl.innerHTML = n ? `${esc(n === 1 ? input.files[0].name : n + ' arquivos selecionados')}<br><small class="mono">clique para trocar</small>` : padrao;
  };
  input.addEventListener('change', atualizar);
  return () => { input.value = ''; atualizar(); };
}
function b64Blob(b64, tipo) {
  const bin = atob(b64), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: tipo });
}
function baixar(blob, nome) {
  const url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = nome; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

/* ============ LOGIN ============ */
// Olho de mostrar/ocultar senha (login e senha da emissão)
document.addEventListener('click', (e) => {
  const b = e.target.closest('.olho'); if (!b) return;
  e.preventDefault();
  const inp = b.parentElement.querySelector('input'), mostrar = inp.type === 'password';
  inp.type = mostrar ? 'text' : 'password';
  b.querySelector('.material-icons').textContent = mostrar ? 'visibility' : 'visibility_off';
  b.setAttribute('aria-label', mostrar ? 'Ocultar senha' : 'Mostrar senha');
  inp.focus();
});
function ocultarSenhas() { // ao sair ou reabrir o login, a senha volta a ficar escondida
  $$('.inp-senha input').forEach((i) => { i.type = 'password'; });
  $$('.olho').forEach((b) => { b.querySelector('.material-icons').textContent = 'visibility_off'; b.setAttribute('aria-label', 'Mostrar senha'); });
}
const estado = { emissao: false };
function mostrarLogin(msg = '') {
  $('#tela-app').hidden = true; $('#tela-login').hidden = false;
  $('#login-erro').textContent = msg; $('#senha').value = ''; ocultarSenhas(); $('#senha').focus();
}
function entrarApp(s) {
  estado.emissao = !!s.emissao;
  $('#tela-login').hidden = true; $('#tela-app').hidden = false;
  window.scrollTo(0, 0);
  embaralhar($('.aba[aria-selected="true"] .aba-nome'));
  carregarEnvios(); carregarOpcoes(); renderPortaoEmissao();
}
async function entrar() {
  const senha = $('#senha').value;
  if (!senha) { $('#login-erro').textContent = 'Digite a senha.'; $('#senha').focus(); return; }
  try {
    await ocupado($('#b-entrar'), 'Entrando…', () => api('/api/login', { metodo: 'POST', json: { senha } }));
    entrarApp({ emissao: false });
  } catch (e) { $('#login-erro').textContent = e.message; $('#senha').select(); }
}
$('#b-entrar').addEventListener('click', entrar);
$('#senha').addEventListener('keydown', (e) => { if (e.key === 'Enter') entrar(); });
$('#senha').addEventListener('input', () => { $('#login-erro').textContent = ''; });
$('#b-sair').addEventListener('click', async () => { try { await api('/api/sair', { metodo: 'POST' }); } catch { /* sai mesmo assim */ } mostrarLogin(); });

/* ============ ABAS ============ */
const abas = $$('.aba');
function ativar(aba, foco) {
  abas.forEach((a) => {
    const sim = a === aba;
    a.setAttribute('aria-selected', String(sim));
    a.tabIndex = sim ? 0 : -1;
    $('#' + a.getAttribute('aria-controls')).hidden = !sim;
  });
  embaralhar(aba.querySelector('.aba-nome'));
  if (foco) aba.focus();
}
abas.forEach((a, i) => {
  a.addEventListener('click', () => ativar(a));
  a.addEventListener('keydown', (e) => {
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (d) { e.preventDefault(); ativar(abas[(i + d + abas.length) % abas.length], true); }
  });
});

/* ============ ACOMPANHAMENTO ============ */
let linhas = [], HOJE = '';
// Mesma classificação do dashboard.py (a última regra que bate vence)
function categoria(s) {
  const u = String(s).toUpperCase(); let c = 'Erros / atraso';
  if (/DELIVERED|ENTREGUE|PICKED UP/.test(u)) c = 'Entregues';
  if (/TRANSIT|WAY|ACCEPT|PROGRESS|GERADA|COLETA|OUT FOR DELIVERY/.test(u)) c = 'Em trânsito';
  if (/ERROR|ALERT|DEVOLVIDO|UNAVAILABLE|AGUARDANDO|PRE TRANSIT/.test(u)) c = 'Pendentes de envio';
  return c;
}
const CATS = [
  { nome: 'Pendentes de envio', cor: 'var(--salmao)' },
  { nome: 'Entregues', cor: 'var(--verde)' },
  { nome: 'Em trânsito', cor: 'var(--blue-2)' },
  { nome: 'Erros / atraso', cor: 'var(--muted)' },
];
const corDe = (s) => CATS.find((c) => c.nome === categoria(s)).cor;
const sel = { imp: new Set(), exc: new Set() };
let pdfPronto = null; // { chave, blob, nao }

async function carregarEnvios() {
  $('#contagem').textContent = '[ carregando… ]';
  try {
    const r = await api('/api/envios');
    linhas = r.linhas; HOJE = r.hoje;
    const existentes = new Set(linhas.map((l) => l.numero));
    [sel.imp, sel.exc].forEach((s) => s.forEach((n) => { if (!existentes.has(n)) s.delete(n); }));
    renderAcomp();
  } catch (e) { if (!silencioso(e)) { $('#contagem').textContent = '[ erro ao carregar ]'; toast(esc(e.message), 'erro'); } }
}
function filtradas() {
  const q = $('#busca').value.trim().toUpperCase();
  if (!q) return linhas;
  const m = q.match(/^(\d+)\s*·/);
  if (m) return linhas.filter((l) => l.pedido === m[1]);
  return linhas.filter((l) => l.pedido.includes(q) || l.nome.toUpperCase().includes(q));
}
function renderKpis() {
  const cont = Object.fromEntries(CATS.map((c) => [c.nome, 0]));
  linhas.forEach((l) => { cont[categoria(l.status)]++; });
  const total = linhas.length;
  const pct = (v) => (total ? Math.round((v / total) * 100) : 0) + '%';
  const blocos = [
    { r: 'Total', v: total, cor: 'var(--line-2)', p: '' },
    { r: 'Em trânsito', v: cont['Em trânsito'], cor: 'var(--blue-2)', p: pct(cont['Em trânsito']) },
    { r: 'Entregues', v: cont['Entregues'], cor: 'var(--verde)', p: pct(cont['Entregues']) },
    { r: 'Pendentes de envio', v: cont['Pendentes de envio'], cor: 'var(--salmao)', p: pct(cont['Pendentes de envio']) },
  ];
  $('#kpis').innerHTML = blocos.map((b) => `<div class="kpi" style="--c:${b.cor}"><span class="eyebrow">${b.r}</span><span class="kpi-linha"><span class="kpi-valor">${b.v}</span><span class="kpi-pct">${b.p}</span></span></div>`).join('');
  // rosca: um arco por categoria, cada um começando onde o anterior terminou
  const raio = 84, volta = 2 * Math.PI * raio, folga = total > 1 ? 3 : 0;
  let inicio = 0;
  const ordem = CATS.filter((c) => cont[c.nome]).sort((a, b) => cont[b.nome] - cont[a.nome]);
  $('#g-rosca').innerHTML = ordem.map((c) => {
    const tam = (cont[c.nome] / total) * volta;
    const arco = `<circle cx="110" cy="110" r="${raio}" stroke="${c.cor}" stroke-dasharray="${Math.max(0, tam - folga)} ${volta}" stroke-dashoffset="${-inicio}" transform="rotate(-90 110 110)"/>`;
    inicio += tam; return arco;
  }).join('') + `<text class="total" x="110" y="114" text-anchor="middle">${total}</text><text class="rot" x="110" y="138" text-anchor="middle">envios</text>`;
  $('#g-rosca').setAttribute('aria-label', 'Distribuição de status: ' + ordem.map((c) => `${c.nome} ${pct(cont[c.nome])}`).join(', '));
  $('#g-legenda').innerHTML = ordem.map((c) => `<li><span class="ponto" style="--c:${c.cor}"></span>${c.nome} <b>${pct(cont[c.nome])}</b></li>`).join('');
  const maior = Math.max(1, ...CATS.map((c) => cont[c.nome]));
  const barras = CATS.slice().sort((a, b) => cont[b.nome] - cont[a.nome]);
  $('#g-barras').innerHTML = barras.map((c) => `<div class="barra" title="${c.nome}: ${cont[c.nome]}"><b>${cont[c.nome]}</b><i style="--c:${c.cor};height:${cont[c.nome] ? Math.max(4, (cont[c.nome] / maior) * 236) : 2}px"></i></div>`).join('');
  $('#g-barras-rot').innerHTML = barras.map((c) => `<span>${c.nome}</span>`).join('');
}
function renderOpcoes() {
  const mapa = new Map();
  linhas.forEach((l) => { if (!l.pedido) return; if (!mapa.has(l.pedido)) mapa.set(l.pedido, new Set()); if (l.nome) mapa.get(l.pedido).add(l.nome.toUpperCase()); });
  $('#opcoes').innerHTML = [...mapa.entries()].sort().map(([p, n]) => `<option value="${esc(n.size ? p + ' · ' + [...n].sort().join(' / ') : p)}"></option>`).join('');
}
function renderTabela() {
  const vis = filtradas(), q = $('#busca').value.trim();
  $('#b-limpar').hidden = !q;
  $('#contagem').textContent = q ? `[ ${vis.length} de ${linhas.length} envios ]` : `[ ${linhas.length} envios ]`;
  if (!vis.length) { $('#corpo').innerHTML = `<tr><td class="vazio" colspan="10">${q ? `Nenhum envio encontrado para “${esc(q)}”.` : 'Nenhuma etiqueta cadastrada na planilha ainda.'}</td></tr>`; return; }
  $('#corpo').innerHTML = vis.map((l) => {
    const n = l.numero, ok = !!n, hoje = HOJE && l.ult.startsWith(HOJE);
    const tarefa = l.tarefa.startsWith('https://') ? `<a class="lnk" href="${esc(l.tarefa)}" target="_blank" rel="noopener"><i class="material-icons">open_in_new</i>Abrir</a>` : '<span class="mono">—</span>';
    const rastreio = ok ? `<a class="lnk" href="${LINK_USPS + n}" target="_blank" rel="noopener"><i class="material-icons">local_shipping</i><small>…${n.slice(-6)}</small></a>` : '<span class="mono">—</span>';
    return `<tr class="${hoje ? 'hoje' : ''}${sel.exc.has(n) ? ' marcada-exc' : ''}">
      <td class="c"><input type="checkbox" data-acao="imp" data-r="${n}" aria-label="Imprimir etiqueta do pedido ${esc(l.pedido)} ${esc(l.tipo)}"${sel.imp.has(n) ? ' checked' : ''}${ok ? '' : ' disabled'}></td>
      <td class="num">${esc(l.data)}</td>
      <td class="num">${esc(l.pedido)}</td>
      <td>${tarefa}</td>
      <td class="quebra">${esc(l.nome)}</td>
      <td>${rastreio}</td>
      <td><span class="tipo">${esc(l.tipo)}</span></td>
      <td class="quebra st"><span class="status" title="${esc(l.status)}"><span class="ponto" style="--c:${corDe(l.status)}"></span><span>${esc(l.status)}</span></span></td>
      <td class="num fraco">${esc(l.ult)}</td>
      <td class="c"><input type="checkbox" data-acao="exc" data-r="${n}" aria-label="Excluir linha do pedido ${esc(l.pedido)} ${esc(l.tipo)}"${sel.exc.has(n) ? ' checked' : ''}${ok ? '' : ' disabled'}></td>
    </tr>`;
  }).join('');
}
const descricao = (n) => { const l = linhas.find((x) => x.numero === n); return l ? `#${esc(l.pedido)} ${esc(l.tipo)} (…${n.slice(-6)})` : `…${n.slice(-6)}`; };
const chaveImp = () => [...sel.imp].sort().join(',');
function renderBarras() {
  const imp = [...sel.imp], exc = [...sel.exc];
  if (imp.length) {
    const pronto = pdfPronto && pdfPronto.chave === chaveImp();
    const aviso = pronto && pdfPronto.nao.length
      ? `<span style="color:var(--ambar)">⚠️ Sem etiqueta para reimprimir (não emitida por este sistema ou com mais de 90 dias): ${pdfPronto.nao.map((r) => '…' + esc(r.slice(-6))).join(', ')}</span>` : '';
    $('#barra-imp').innerHTML = `<div class="alerta info"><i class="material-icons">print</i><div class="corpo">
      <span>Selecionadas para imprimir: <b>${imp.map(descricao).join(', ')}</b></span>${aviso}
      <div class="acoes">${pronto
        ? `<button class="btn" id="b-baixar-pdf"><i class="material-icons">download</i>Baixar etiquetas (PDF)</button>`
        : `<button class="btn" id="b-preparar"><i class="material-icons">print</i>Preparar PDF das etiquetas</button>`}
        <button class="btn sec" id="b-limpar-imp">Desmarcar</button></div></div></div>`;
  } else $('#barra-imp').innerHTML = '';
  $('#barra-exc').innerHTML = exc.length ? `<div class="alerta erro"><i class="material-icons">delete</i><div class="corpo">
      <span>Selecionados para exclusão: <b>${exc.map(descricao).join(', ')}</b></span>
      <div class="acoes"><button class="btn perigo" id="b-excluir">Confirmar exclusão</button><button class="btn sec" id="b-limpar-exc">Cancelar</button></div></div></div>` : '';
}
function renderAcomp() { renderKpis(); renderOpcoes(); renderTabela(); renderBarras(); }

$('#busca').addEventListener('input', renderTabela);
$('#b-limpar').addEventListener('click', () => { $('#busca').value = ''; renderTabela(); $('#busca').focus(); });
$('#corpo').addEventListener('change', (e) => {
  const cb = e.target.closest('input[data-acao]'); if (!cb || !cb.dataset.r) return;
  const s = sel[cb.dataset.acao];
  cb.checked ? s.add(cb.dataset.r) : s.delete(cb.dataset.r);
  if (cb.dataset.acao === 'exc') cb.closest('tr').classList.toggle('marcada-exc', cb.checked);
  renderBarras();
});
document.addEventListener('click', async (e) => {
  const b = e.target.closest('button'); if (!b || !b.id) return;
  if (b.id === 'b-preparar') {
    const rastreios = [...sel.imp], chave = chaveImp();
    try {
      const r = await ocupado(b, 'Buscando as etiquetas…', () => api('/api/envios/imprimir', { metodo: 'POST', json: { rastreios }, bruto: true }));
      const nao = (r.headers.get('X-Nao-Achados') || '').split(',').filter(Boolean);
      pdfPronto = { chave, blob: await r.blob(), nao };
      renderBarras();
    } catch (err) {
      if (silencioso(err)) return;
      toast(esc(err.message), err.status === 404 ? 'aviso' : 'erro', 6500);
    }
  } else if (b.id === 'b-baixar-pdf') {
    baixar(pdfPronto.blob, `Etiquetas_${HOJE || 'reimpressao'}.pdf`);
  } else if (b.id === 'b-limpar-imp') {
    sel.imp.clear(); pdfPronto = null; renderTabela(); renderBarras();
  } else if (b.id === 'b-limpar-exc') {
    sel.exc.clear(); renderTabela(); renderBarras();
  } else if (b.id === 'b-excluir') {
    const rastreios = [...sel.exc];
    try {
      const r = await ocupado(b, 'Excluindo…', () => api('/api/envios/excluir', { metodo: 'POST', json: { rastreios } }));
      const apagados = rastreios.length - r.nao_apagados.length;
      sel.exc.clear(); rastreios.forEach((n) => sel.imp.delete(n));
      if (r.nao_apagados.length) toast(`Não foi possível excluir os rastreios ${r.nao_apagados.map(esc).join(', ')}. Recarregue e confira a planilha.`, 'erro', 7000);
      if (apagados) toast(`${apagados} ${apagados === 1 ? 'linha excluída' : 'linhas excluídas'} da planilha.`, 'ok');
      await carregarEnvios();
    } catch (err) { if (!silencioso(err)) toast(esc(err.message), 'erro'); }
  }
});
$('#b-recarregar').addEventListener('click', (e) => ocupado(e.currentTarget, 'Carregando…', carregarEnvios));
async function acaoLonga(btn, rota, texto, ok) {
  try {
    await ocupado(btn, texto, () => api(rota, { metodo: 'POST' }));
    toast(ok, 'ok'); await carregarEnvios();
  } catch (e) { if (!silencioso(e)) toast(esc(e.message), 'erro'); }
}
$('#b-bitrix').addEventListener('click', (e) => acaoLonga(e.currentTarget, '/api/acoes/bitrix', 'Consultando o Bitrix…', 'Links de tarefas atualizados.'));
$('#b-usps').addEventListener('click', (e) => acaoLonga(e.currentTarget, '/api/acoes/usps', 'Consultando a USPS (pode levar alguns minutos)…', 'Rastreios atualizados.'));

/* ============ EMITIR ============ */
const ROTULOS = { nome: 'Nome', endereco: 'Endereço', cidade: 'Cidade', estado: 'Estado', zip: 'ZIP', telefone: 'Telefone' };
const em = { opcoes: null, modo: 'IDA', quais: 'Ambas', teto: null };
arquivo($('#emi-drop'), $('#emi-arq'), $('#emi-drop-txt'));

function renderPortaoEmissao() {
  $('#emi-gate').hidden = estado.emissao;
  $('#emi-corpo').hidden = !estado.emissao;
}
async function liberarEmissao() {
  const senha = $('#emi-senha').value;
  if (!senha) { $('#emi-gate-erro').textContent = 'Digite a senha da emissão.'; return; }
  try {
    await ocupado($('#b-liberar'), 'Liberando…', () => api('/api/emissao/liberar', { metodo: 'POST', json: { senha } }));
    estado.emissao = true; $('#emi-senha').value = ''; $('#emi-gate-erro').textContent = '';
    renderPortaoEmissao(); carregarOpcoes();
  } catch (e) { if (!silencioso(e)) { $('#emi-gate-erro').textContent = e.message; $('#emi-senha').select(); } }
}
$('#b-liberar').addEventListener('click', liberarEmissao);
$('#emi-senha').addEventListener('keydown', (e) => { if (e.key === 'Enter') liberarEmissao(); });

async function carregarOpcoes() {
  try {
    const o = await api('/api/emissao/opcoes');
    const primeira = !em.opcoes;
    em.opcoes = o; em.teto = o.teto;
    if (primeira) {
      seg($('#seg-modo'), 'modo', Object.keys(o.modos), em.modo, (v) => { em.modo = v; em.quais = 'Ambas'; renderQuais(); renderEmitir(); });
      renderQuais();
      $('#sel-cons').innerHTML = o.consulados.map((c) => `<option>${esc(c)}</option>`).join('');
      $('#l228-cons').innerHTML = $('#sel-cons').innerHTML;
      $('#sel-dpt').innerHTML = o.departamentos.map((d) => `<option>${esc(d)}</option>`).join('');
      $('#campos').innerHTML = o.campos.map((k) => `<label class="campo"><span>${ROTULOS[k] || k}${o.obrigatorios.includes(k) ? ' *' : ''}</span><input class="inp" id="cli-${k}" autocomplete="off" maxlength="120"></label>`).join('');
    }
    renderLeituras(o.leituras);
    renderEmitir();
  } catch (e) { if (!silencioso(e)) toast(esc(e.message), 'erro'); }
}
function renderQuais() {
  seg($('#seg-quais'), 'quais', ['Ambas', 'Cli - Con', 'Con - Cli'], em.quais, (v) => { em.quais = v; renderEmitir(); });
}
function renderLeituras(l) { if (l) $('#leituras').textContent = `[ leituras da IA hoje: ${l.total} de ${l.limite} ]`; }
const trechosAtuais = () => {
  const t = em.opcoes ? em.opcoes.modos[em.modo] : [];
  return em.modo === 'Cli - Con / Con - Cli' && em.quais !== 'Ambas' ? t.filter((x) => x[0] === em.quais) : t;
};
const ehDpt = () => em.modo.startsWith('D55');
const precisaEndereco = () => !ehDpt() || (em.opcoes && $('#sel-dpt').value === em.opcoes.outro_dpt);
const dadosEndereco = () => Object.fromEntries((em.opcoes ? em.opcoes.campos : []).map((k) => [k, $('#cli-' + k).value.trim()]));

function renderTeto() {
  const t = em.teto;
  if (!t || t.erro) {
    $('#teto-qtd').textContent = '—'; $('#teto-gasto').textContent = '—';
    $('#trilho-qtd i').style.width = '0'; $('#trilho-gasto i').style.width = '0';
    return;
  }
  $('#teto-qtd').textContent = `${t.qtd} / ${t.max_qtd}`;
  $('#teto-gasto').textContent = `${usd(t.gasto)} / ${t.max_usd.toFixed(0)}`;
  $('#trilho-qtd i').style.width = Math.min(100, (t.qtd / t.max_qtd) * 100) + '%';
  $('#trilho-gasto i').style.width = Math.min(100, (t.gasto / t.max_usd) * 100) + '%';
  $('#trilho-qtd').classList.toggle('cheio', t.qtd >= t.max_qtd);
  $('#trilho-gasto').classList.toggle('cheio', t.gasto >= t.max_usd);
}
function renderEmitir() {
  if (!em.opcoes) return;
  const trechos = trechosAtuais(), tipos = trechos.map((t) => t[0]), n = trechos.length;
  const usaCon = trechos.some(([, de, para]) => de === 'CON' || para === 'CON');
  $('#w-quais').hidden = em.modo !== 'Cli - Con / Con - Cli';
  $('#w-cons').hidden = !usaCon;
  $('#w-dpt').hidden = !ehDpt();
  $('#w-end').hidden = !precisaEndereco();
  $('#end-titulo').textContent = ehDpt() ? 'Endereço do departamento' : 'Endereço do cliente';
  const pedido = $('#emi-pedido').value.trim();
  const repetidas = pedido ? [...new Set(linhas.filter((l) => l.pedido === pedido && tipos.includes(l.tipo)).map((l) => l.tipo))] : [];
  const faltando = precisaEndereco() ? em.opcoes.obrigatorios.filter((k) => !$('#cli-' + k).value.trim()) : [];
  const forcar = $('#emi-forcar') ? $('#emi-forcar').checked : false;
  const t = em.teto;
  const dentroTeto = !!t && !t.erro && t.qtd + n <= t.max_qtd && t.gasto < t.max_usd;
  const avisos = [];
  if (pedido && !/^\d+$/.test(pedido)) avisos.push(`<p class="alerta erro"><i class="material-icons">error</i><span>O número do pedido deve ter só dígitos.</span></p>`);
  if (repetidas.length) avisos.push(`<div class="alerta aviso"><i class="material-icons">warning</i><div class="corpo"><span>O pedido <b>${esc(pedido)}</b> já tem etiqueta <b>${repetidas.map(esc).join(', ')}</b> na planilha.</span><label class="check"><input type="checkbox" id="emi-forcar"${forcar ? ' checked' : ''}> Emitir mesmo assim (vai cobrar de novo)</label></div></div>`);
  if (t && t.erro) avisos.push(`<p class="alerta erro"><i class="material-icons">block</i><span>${esc(t.erro)}</span></p>`);
  else if (t && !dentroTeto) avisos.push(`<p class="alerta erro"><i class="material-icons">block</i><span>Teto diário de compras atingido. Novas compras só amanhã.</span></p>`);
  if (faltando.length) avisos.push(`<p class="nota">Faltando: ${faltando.map((k) => (ROTULOS[k] || k).toLowerCase()).join(', ')}</p>`);
  $('#emi-avisos').innerHTML = avisos.join('');
  if ($('#emi-forcar')) $('#emi-forcar').addEventListener('change', renderEmitir);
  const pronto = /^\d+$/.test(pedido) && !faltando.length && (!repetidas.length || forcar) && dentroTeto;
  const b = $('#b-comprar');
  if (!b.querySelector('.gira')) {
    b.disabled = !pronto;
    b.innerHTML = `<i class="material-icons">credit_card</i>Comprar ${n} etiqueta${n > 1 ? 's' : ''}`;
  }
  renderTeto();
}
['#emi-pedido', '#sel-cons', '#sel-dpt'].forEach((s) => $(s).addEventListener(s === '#emi-pedido' ? 'input' : 'change', renderEmitir));
$('#campos').addEventListener('input', renderEmitir);

$('#b-ler').addEventListener('click', async (e) => {
  const texto = $('#emi-txt').value.trim(), arq = $('#emi-arq').files[0];
  if (!texto && !arq) { toast('Envie um comprovante (ou a Driver\'s License) ou cole o endereço.', 'aviso'); return; }
  const form = new FormData(); form.append('texto', texto); if (arq) form.append('arquivo', arq);
  try {
    const r = await ocupado(e.currentTarget, 'Lendo com a IA…', () => api('/api/endereco/ler', { metodo: 'POST', form }));
    em.opcoes.campos.forEach((k) => { $('#cli-' + k).value = r.dados[k] || ''; });
    renderLeituras(r.leituras); renderEmitir();
    toast('Endereço lido. Confira os campos antes de comprar.', 'ok');
  } catch (err) { if (!silencioso(err)) toast(esc(err.message), 'erro', 6500); }
});

$('#b-comprar').addEventListener('click', async (e) => {
  const pedido = $('#emi-pedido').value.trim(), end = dadosEndereco();
  const corpo = {
    pedido, modo: em.modo, quais: em.quais, consulado: $('#sel-cons').value, departamento: $('#sel-dpt').value,
    cliente: ehDpt() ? null : end, endereco_departamento: ehDpt() && precisaEndereco() ? end : null,
    forcar: $('#emi-forcar') ? $('#emi-forcar').checked : false,
  };
  const n = trechosAtuais().length;
  if (!confirm(`Comprar ${n} etiqueta${n > 1 ? 's' : ''} para o pedido #${pedido}? A compra é cobrada na hora.`)) return;
  let r;
  try {
    r = await ocupado(e.currentTarget, 'Comprando…', () => api('/api/emissao/comprar', { metodo: 'POST', json: corpo }));
  } catch (err) {
    if (!silencioso(err)) toast(esc(err.message), 'erro', 7000);
    renderEmitir(); return;
  }
  if (r.teto) em.teto = r.teto;
  await carregarEnvios();
  const cards = r.etiquetas.map((c, i) => `<div class="etq-card"><div class="etq-info"><b>${esc(c.tipo)}</b><span>${usd(c.custo)}</span></div>
    <img class="etq-img" src="data:image/png;base64,${c.png}" alt="Etiqueta ${esc(c.tipo)}">
    <span class="mono">${esc(c.rastreio)}</span>
    <button class="btn sec" data-pdf="${i}"><i class="material-icons">download</i>Baixar PDF para imprimir</button></div>`);
  if (r.label_228) cards.push(`<div class="etq-card"><div class="etq-info"><b>Label 228</b><span>envelope</span></div>
    <img class="etq-img" src="data:image/png;base64,${r.label_228}" alt="Label 228"><button class="btn sec" data-l228="1"><i class="material-icons">download</i>Baixar Label 228</button></div>`);
  const ok = r.etiquetas.length ? `<p class="alerta ok"><i class="material-icons">check_circle</i><span>${r.etiquetas.length} etiqueta${r.etiquetas.length > 1 ? 's' : ''} do pedido <b>#${esc(r.pedido)}</b> compradas e registradas. O PDF sai deitado na metade de cima da folha: imprima em tamanho real (100%).</span></p>` : '';
  const erro = r.erro ? `<p class="alerta erro"><i class="material-icons">error</i><span>${esc(r.erro)}</span></p>` : '';
  $('#emi-resultado').innerHTML = ok + erro + (cards.length ? `<div class="resultado">${cards.join('')}</div>` : '');
  $('#emi-resultado')._dados = r;
  $('#emi-resultado').scrollIntoView({ behavior: reduz.matches ? 'auto' : 'smooth', block: 'start' });
  renderEmitir();
});
$('#emi-resultado').addEventListener('click', (e) => {
  const r = $('#emi-resultado')._dados; if (!r) return;
  const bp = e.target.closest('[data-pdf]'), bl = e.target.closest('[data-l228]');
  if (bp) { const c = r.etiquetas[Number(bp.dataset.pdf)]; baixar(b64Blob(c.pdf, 'application/pdf'), `Etiqueta_${r.pedido}_${c.tipo.replace(/\s/g, '')}.pdf`); }
  if (bl) baixar(b64Blob(r.label_228, 'image/png'), `Label_Passaporte_${r.pedido}.png`);
});

// Reembolso
$('#b-ree').addEventListener('click', async (e) => {
  const rastreio = digitos($('#ree-r').value);
  if (!rastreio) { toast('Digite o rastreio da etiqueta.', 'aviso'); return; }
  try {
    const c = await ocupado(e.currentTarget, 'Procurando a compra…', () => api('/api/reembolso/consultar', { metodo: 'POST', json: { rastreio } }));
    $('#ree-res').innerHTML = c.bloqueio
      ? `<p class="alerta erro"><i class="material-icons">block</i><span>${esc(c.bloqueio)}</span></p>`
      : `<div class="alerta info"><i class="material-icons">receipt_long</i><div class="corpo"><span><b>${esc(c.referencia || 'sem referência')}</b> · comprada em ${esc(c.criada)} · ${usd(c.valor)} · status USPS: ${esc(c.status_usps)}</span>
        <div class="acoes"><button class="btn perigo" id="b-ree-ok" data-r="${esc(c.rastreio)}"><i class="material-icons">undo</i>Confirmar reembolso (irreversível)</button></div></div></div>`;
  } catch (err) { if (!silencioso(err)) $('#ree-res').innerHTML = `<p class="alerta erro"><i class="material-icons">error</i><span>${esc(err.message)}</span></p>`; }
});
$('#ree-res').addEventListener('click', async (e) => {
  const b = e.target.closest('#b-ree-ok'); if (!b) return;
  try {
    const r = await ocupado(b, 'Pedindo reembolso…', () => api('/api/reembolso/confirmar', { metodo: 'POST', json: { rastreio: b.dataset.r } }));
    const extras = [r.nao_apagado ? 'Rastreio não encontrado no painel: nada foi apagado lá.' : 'A linha saiu do painel.',
      r.auditoria_ok ? `A auditoria recebeu −${usd(r.valor)}.` : `Não gravou na auditoria: lance à mão −${usd(r.valor)}.`];
    $('#ree-res').innerHTML = `<p class="alerta ok"><i class="material-icons">check_circle</i><span>Reembolso solicitado (status ${esc(r.status)}). O crédito pode levar até 14 dias. ${extras.map(esc).join(' ')}</span></p>`;
    $('#ree-r').value = '';
    carregarEnvios();
  } catch (err) { if (!silencioso(err)) $('#ree-res').innerHTML = `<p class="alerta erro"><i class="material-icons">error</i><span>${esc(err.message)}</span></p>`; }
});

/* ============ RASTREIO ANTIGO ============ */
const PARES = { 'IDA + RETORNO': ['IDA', 'Esc → Cli', 'RETORNO', 'Cli → Esc'], 'Cli - Con / Con - Cli': ['Cli - Con', 'Cli → Con', 'Con - Cli', 'Con → Cli'] };
let tipoAntigo = 'IDA';
seg($('#seg-antigo'), 'antigo', ['IDA', 'RETORNO', ...Object.keys(PARES)], tipoAntigo, (v) => { tipoAntigo = v; renderAntigo(); });
function renderAntigo() {
  const par = PARES[tipoAntigo];
  $('#w-ant-r2').hidden = !par;
  $('#ant-r1-rot').textContent = par ? `Rastreio USPS – ida (${par[1]}) *` : 'Rastreio USPS *';
  if (par) $('#ant-r2-rot').textContent = `Rastreio USPS – volta (${par[3]}) *`;
  $('#antigo-info').innerHTML = par ? `<p class="alerta info"><i class="material-icons">info</i><span>Este tipo gera duas etiquetas: elas entram em linhas separadas (<b>${par[0]}</b> e <b>${par[2]}</b>).</span></p>` : '';
}
renderAntigo();
$('#ant-data').value = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
$('#b-antigo').addEventListener('click', async (e) => {
  const par = PARES[tipoAntigo];
  const corpo = { tipo: tipoAntigo, pedido: $('#ant-pedido').value.trim(), nome: $('#ant-nome').value.trim(),
    rastreio: $('#ant-r1').value.trim(), rastreio_volta: $('#ant-r2').value.trim(), data: $('#ant-data').value };
  if (!corpo.pedido || !corpo.nome || !corpo.rastreio || !corpo.data || (par && !corpo.rastreio_volta)) { toast('Preencha os campos obrigatórios (*).', 'aviso'); return; }
  if (par && corpo.rastreio === corpo.rastreio_volta) { toast('O rastreio da ida e o da volta não podem ser iguais.', 'aviso'); return; }
  try {
    const r = await ocupado(e.currentTarget, 'Adicionando à planilha…', () => api('/api/antigo', { metodo: 'POST', json: corpo }));
    const falhas = r.resultados.filter((x) => !x.ok).map((x) => x.tipo), gravados = r.resultados.filter((x) => x.ok).map((x) => x.tipo);
    if (!falhas.length) {
      toast(`Etiqueta de <b>${esc(corpo.nome)}</b> cadastrada (${gravados.map(esc).join(' + ')}) com data ${fmtBR(corpo.data)}.`, 'ok');
      ['#ant-pedido', '#ant-nome', '#ant-r1', '#ant-r2'].forEach((s) => { $(s).value = ''; });
    } else {
      toast(`Falha ao cadastrar: ${falhas.map(esc).join(', ')}.${gravados.length ? ` Já foi gravado: ${gravados.map(esc).join(', ')}. Confira a planilha antes de tentar de novo para não duplicar.` : ''}`, 'erro', 9000);
    }
    carregarEnvios();
  } catch (err) { if (!silencioso(err)) toast(esc(err.message), 'erro'); }
});
arquivo($('#l228-drop'), $('#l228-arq'), $('#l228-drop-txt'));
$('#b-228').addEventListener('click', async (e) => {
  const texto = $('#l228-txt').value.trim(), arq = $('#l228-arq').files[0];
  if (!texto && !arq) { toast('Envie o comprovante (ou a Driver\'s License) ou cole o endereço.', 'aviso'); return; }
  const form = new FormData(); form.append('consulado', $('#l228-cons').value); form.append('texto', texto); if (arq) form.append('arquivo', arq);
  try {
    const r = await ocupado(e.currentTarget, 'Lendo com a IA…', () => api('/api/label228', { metodo: 'POST', form }));
    renderLeituras(r.leituras);
    $('#l228-res').innerHTML = `<div class="g2" style="align-items:start"><img class="l228-img" src="data:image/png;base64,${r.png}" alt="Label 228 gerada">
      <div class="painel-aba" style="gap:12px"><p class="nota">Confira o nome e o endereço na label. Se algo saiu errado, cole o endereço correto acima e gere de novo.</p>
      <div><button class="btn sec" id="b-228-baixar"><i class="material-icons">download</i>Baixar label (PNG)</button></div></div></div>`;
    $('#b-228-baixar').onclick = () => baixar(b64Blob(r.png, 'image/png'), r.arquivo);
  } catch (err) { if (!silencioso(err)) toast(esc(err.message), 'erro', 7000); }
});

/* ============ FOTO DOS SELOS ============ */
let fotoLidas = null, conferencia = [], tempoConf = 0;
const limparFotos = arquivo($('#foto-drop'), $('#foto-arq'), $('#foto-drop-txt'));
$('#b-ler-fotos').addEventListener('click', async (e) => {
  const arqs = [...$('#foto-arq').files];
  if (!arqs.length) { toast('Escolha as fotos das etiquetas.', 'aviso'); return; }
  const form = new FormData(); arqs.forEach((f) => form.append('fotos', f));
  try {
    const r = await ocupado(e.currentTarget, 'Lendo as etiquetas com a IA…', () => api('/api/fotos/ler', { metodo: 'POST', form }));
    renderLeituras(r.leituras);
    r.erros.forEach((m) => toast(esc(m), 'erro', 7000));
    if (!r.lidas.length) { toast('Nenhuma etiqueta identificada.', 'aviso'); return; }
    fotoLidas = r.lidas.map((l) => ({ pedido: l.pedido, rastreio: l.rastreio, salvar: true }));
    $('#foto-res').hidden = false; $('#foto-susp').checked = false;
    cantos($('#foto-res'));
    renderFotoEdit(); await conferir();
  } catch (err) { if (!silencioso(err)) toast(esc(err.message), 'erro'); }
});
function renderFotoEdit() {
  $('#foto-edit').innerHTML = fotoLidas.map((l, i) => `<tr>
    <td class="c"><input type="checkbox" data-i="${i}" data-k="salvar"${l.salvar ? ' checked' : ''} aria-label="Salvar linha ${i + 1}"></td>
    <td><input class="inp mono-inp" data-i="${i}" data-k="pedido" value="${esc(l.pedido)}" aria-label="Pedido da linha ${i + 1}" style="min-height:38px"></td>
    <td><input class="inp mono-inp" data-i="${i}" data-k="rastreio" value="${esc(l.rastreio)}" aria-label="Rastreio da linha ${i + 1}" style="min-height:38px"></td></tr>`).join('');
}
async function conferir() {
  const minha = ++tempoConf;
  try {
    const r = await api('/api/fotos/conferir', { metodo: 'POST', json: { linhas: fotoLidas } });
    if (minha !== tempoConf) return; // já tem uma conferência mais nova a caminho
    conferencia = r.conferencia; renderFotoConf();
  } catch (err) { if (!silencioso(err)) toast(esc(err.message), 'erro'); }
}
let atrasoConf = 0;
const conferirDepois = () => { clearTimeout(atrasoConf); atrasoConf = setTimeout(conferir, 500); };
function renderFotoConf() {
  const cor = { ok: 'var(--verde)', suspeito: 'var(--ambar)', bloqueado: 'var(--erro)' };
  $('#foto-conf').innerHTML = conferencia.length ? conferencia.map((c) => `<tr><td class="num">${esc(c.pedido)}</td><td>${esc(c.nome) || '<span class="mono">—</span>'}</td><td class="num">${esc(c.rastreio)}</td>
    <td style="color:${cor[c.nivel]}">${esc(c.situacao)}</td></tr>`).join('')
    : '<tr><td class="vazio" colspan="4">Nenhuma linha marcada para salvar.</td></tr>';
  const aceitos = $('#foto-susp').checked ? ['ok', 'suspeito'] : ['ok'];
  const qtd = conferencia.filter((c) => aceitos.includes(c.nivel)).length;
  const b = $('#b-foto-salvar');
  b.disabled = !qtd;
  b.innerHTML = `<i class="material-icons">save</i>Adicionar ${qtd} etiqueta${qtd === 1 ? '' : 's'} ao monitoramento`;
}
$('#foto-edit').addEventListener('input', (e) => {
  const el = e.target.closest('[data-k]'); if (!el) return;
  fotoLidas[el.dataset.i][el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value;
  conferirDepois();
});
$('#foto-susp').addEventListener('change', renderFotoConf);
$('#b-foto-salvar').addEventListener('click', async (e) => {
  try {
    const r = await ocupado(e.currentTarget, 'Gravando na planilha…', () => api('/api/fotos/salvar', { metodo: 'POST', json: { linhas: fotoLidas, permitir_suspeitos: $('#foto-susp').checked } }));
    if (r.gravados.length) toast(`${r.gravados.length} etiqueta${r.gravados.length === 1 ? '' : 's'} cadastrada${r.gravados.length === 1 ? '' : 's'}: pedidos ${r.gravados.map(esc).join(', ')}.`, 'ok', 6000);
    if (r.falhas.length) toast(`Falha ao cadastrar os pedidos ${r.falhas.map(esc).join(', ')}. Clique de novo: o que já foi gravado não duplica.`, 'erro', 8000);
    if (!r.falhas.length) { fotoLidas = null; $('#foto-res').hidden = true; limparFotos(); }
    else await conferir();
    carregarEnvios();
  } catch (err) { if (!silencioso(err)) toast(esc(err.message), 'erro'); }
});

/* ============ INÍCIO ============ */
cantos();
(async () => {
  try { const s = await api('/api/sessao'); if (s.logado) entrarApp(s); else mostrarLogin(); }
  catch { mostrarLogin('Não consegui falar com o servidor. Recarregue a página.'); }
})();
})();
