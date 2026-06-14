/* placeintel web UI: no-build vanilla JS; dynamic text is escaped before render. */
'use strict';
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, (ch) => ESC_MAP[ch]); }
function toDate(v) {
  if (v == null || v === '') return null;
  const d = typeof v === 'number' && Number.isFinite(v) ? new Date(v > 1e12 ? v : v * 1000) : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}
function relTime(v) {
  const d = toDate(v);
  if (!d) return '—';
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 0) return d.toLocaleDateString('zh-CN'); if (s < 60) return '刚刚';
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`; if (s < 86400) return `${Math.floor(s / 3600)}小时前`;
  return s < 86400 * 30 ? `${Math.floor(s / 86400)}天前` : d.toLocaleDateString('zh-CN');
}
function fmtClock(v) { const d = toDate(v); return d ? d.toTimeString().slice(0, 8) : ''; }
function stars(rating) { const n = Number(rating); return rating != null && Number.isFinite(n) ? `★ ${n.toFixed(1)}` : '★ —'; }
function fmtInt(n) { return n == null ? '—' : String(n); }
function clampInt(v, min, max, dflt) { const n = Math.round(Number(v)); return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : dflt; }
function safeUrl(u) { return /^https?:\/\//i.test(String(u || '')) ? String(u) : null; }
function mdInline(escaped) { return escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/(^|[\s(（，。、；：—])_([^_\n]+)_/g, '$1<em>$2</em>'); }
function mdToHtml(md) {
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of String(md ?? '').split('\n')) {
    const line = esc(raw.replace(/\s+$/, ''));
    let m;
    if ((m = /^###\s+(.+)/.exec(line))) { closeList(); out.push(`<h4>${mdInline(m[1])}</h4>`); }
    else if ((m = /^##\s+(.+)/.exec(line))) { closeList(); out.push(`<h3>${mdInline(m[1])}</h3>`); }
    else if ((m = /^#\s+(.+)/.exec(line))) { closeList(); out.push(`<h2>${mdInline(m[1])}</h2>`); }
    else if ((m = /^&gt;\s?(.*)/.exec(line))) { closeList(); out.push(`<blockquote>${mdInline(m[1])}</blockquote>`); }
    else if ((m = /^\s*[-*]\s+(.+)/.exec(line))) {
      if (list !== 'ul') { closeList(); out.push('<ul>'); list = 'ul'; }
      out.push(`<li>${mdInline(m[1])}</li>`);
    } else if ((m = /^\s*\d+[.)]\s+(.+)/.exec(line))) {
      if (list !== 'ol') { closeList(); out.push('<ol>'); list = 'ol'; }
      out.push(`<li>${mdInline(m[1])}</li>`);
    } else if (!line.trim()) { closeList(); }
    else { closeList(); out.push(`<p>${mdInline(line)}</p>`); }
  }
  closeList();
  return out.join('');
}
async function apiGet(path) {
  const res = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status} — GET ${path}`);
  return res.json();
}
async function apiPost(path, body) {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail || ''; } catch { /* not json */ }
    throw new Error(`HTTP ${res.status} — POST ${path}${detail ? `（${detail}）` : ''}`);
  }
  return res.json();
}
async function apiDelete(path) {
  const res = await fetch(path, { method: 'DELETE', headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status} — DELETE ${path}`);
  return res.json();
}
const POLL_MS = 2000, MAX_POLL_FAILS = 5;
const TX_TARGET_KEY = 'placeintel.translationTarget';
const txTarget = () => (['zh', 'en'].includes(localStorage.getItem(TX_TARGET_KEY)) ? localStorage.getItem(TX_TARGET_KEY) : 'zh');
const txLabel = (target) => (target === 'en' ? 'EN' : '中文');
const STAGES = { plan: { zh: 'AI规划', en: 'plan' }, search: { zh: '搜索', en: 'search' }, filter: { zh: 'AI筛选', en: 'filter' }, reviews: { zh: '抓评价', en: 'reviews' }, embed: { zh: '向量化', en: 'embed' }, report: { zh: '推理报告', en: 'report' }, done: { zh: '完成', en: 'done' } };
const TAB_NAMES = ['scout', 'shop', 'library', 'ask'];
const tabFromHash = () => (TAB_NAMES.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'scout');
const SEARCH_ROW_CHIP_LIMIT = 8, LIBRARY_PAGE_SIZE = 12, LIBRARY_FILTERS = '#library-sort,#library-category,#library-freshness,#library-risk,#library-language,#library-cached,#library-report';
const state = { tab: 'scout', profiles: [], places: [], libraryLoaded: false, libraryLimit: LIBRARY_PAGE_SIZE, libraryCompare: [], jobs: { scout: null, shop: null }, detail: null, detailReturnFocus: null, meta: null, translationTarget: txTarget(), searches: [], commandMode: 'scout', commandManual: false }; // meta={version, reason/translate/embed}
function loadingHtml(msg) { return `<p class="loading">${esc(msg)} <span class="dots">●●●</span></p>`; }
function errorHtml(msg) { return `<div class="error-box"><span class="error-label">出错 error</span>${esc(msg)}</div>`; }
function emptyHtml(msg, gotoTab, gotoLabel) { const btn = gotoTab ? `<button type="button" class="btn-ghost" data-goto="${esc(gotoTab)}">${esc(gotoLabel || '去侦察 →')}</button>` : ''; return `<div class="empty">${esc(msg)}${btn}</div>`; }
const COMMAND_LABELS = { scout: '开始侦察 Scout →', shop: '深挖单店 Shop →', ask: '直接提问 Ask →' };
function commandGuess(text) { const q = text.trim(); if (!q) return { mode: 'scout', reason: '输入需求、店名或 Maps 链接，会自动推荐路径。' }; if (/google\.[^\s]*\/maps|\/maps\/place|maps\.app\.goo\.gl|goo\.gl\/maps/i.test(q)) return { mode: 'shop', reason: '检测到 Maps 链接，推荐单店深挖 Shop。' }; if ((/[?？]/.test(q) || /^(哪|谁|是否|有没有|can|does|do|which|what|where|how)\b/i.test(q)) && state.searches.length) return { mode: 'ask', reason: '像是在问已缓存证据，推荐 Ask。' }; if (q.length <= 60 && !/(找|租|学|推荐|附近|哪家|best|find|near|nearby|rental|lesson|lessons|restaurant|coffee|cafe)/i.test(q)) return { mode: 'shop', reason: '像具体店名，推荐单店深挖 Shop。' }; return { mode: 'scout', reason: '像开放需求，推荐侦察 Scout。' }; }
function setCommandMode(mode, manual = false, reason = '') { state.commandMode = COMMAND_LABELS[mode] ? mode : 'scout'; if (manual) state.commandManual = true; $$('[data-command-mode]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.commandMode === state.commandMode))); const submit = $('#scout-submit'), why = $('#command-reason'); if (submit) submit.textContent = COMMAND_LABELS[state.commandMode]; if (why) why.textContent = reason || `手动选择 ${state.commandMode.toUpperCase()}。`; }
function refreshCommandMode() { const q = $('#scout-query')?.value || ''; if (!q.trim()) state.commandManual = false; if (!state.commandManual) { const g = commandGuess(q); setCommandMode(g.mode, false, g.reason); } }
function matchingScout(query, near) { const q = query.trim().toLowerCase(), n = near.trim().toLowerCase(), fresh = Date.now() / 1000 - 14 * 86400; return state.searches.find((s) => String(s.query || '').trim().toLowerCase() === q && (!n || String(s.location || '').trim().toLowerCase() === n) && Number(s.created_at || 0) >= fresh); }
function renderPlanCard(plan) {
  if (!plan) return '';
  const queries = (plan.queries || []).map((q) => `<span class="chip">${esc(q)}</span>`).join('');
  const metaBits = [plan.near ? `near · ${esc(plan.near)}` : '', plan.profile ? `profile · ${esc(plan.profile)}` : '', plan.report_lang ? `lang · ${esc(plan.report_lang)}` : ''].filter(Boolean).join('<span class="sep">/</span>');
  return `<div class="plan-card"><div class="plan-label">AI 的计划 · the plan</div>${plan.reasoning ? `<p class="plan-reasoning">${esc(plan.reasoning)}</p>` : ''}${plan.intent ? `<p class="plan-intent">意图 — ${esc(plan.intent)}</p>` : ''}${queries ? `<div class="plan-queries"><span class="plan-q-label">实际执行的搜索</span>${queries}</div>` : ''}${metaBits ? `<p class="plan-meta">${metaBits}</p>` : ''}</div>`;
}
function renderVerdicts(verdicts) {
  if (!Array.isArray(verdicts) || !verdicts.length) return '';
  const rows = verdicts.map((v) => `<li class="verdict ${v.relevant ? 'is-kept' : 'is-cut'}"><span class="verdict-mark">${v.relevant ? '✓' : '✕'}</span><span class="verdict-name">${esc(v.name)}</span>${v.reason ? `<span class="verdict-reason chip">${esc(v.reason)}</span>` : ''}</li>`).join('');
  return `<ul class="verdicts">${rows}</ul>`;
}
function renderEvent(ev) {
  const meta = STAGES[ev.stage] || { zh: ev.stage || '…', en: '' };
  let extra = '';
  if (ev.stage === 'plan' && ev.data) extra = renderPlanCard(ev.data);
  if (ev.stage === 'filter' && ev.data) extra = renderVerdicts(ev.data.verdicts);
  const tone = /重试|retry/i.test(ev.msg || '') ? ' tl-retry' : /缓存|cache/i.test(ev.msg || '') ? ' tl-cache' : '';
  return `<li class="tl-item tl-${esc(ev.stage || 'misc')}${ev.stage === 'done' ? ' tl-done' : ''}${tone}"><span class="tl-dot"></span><div class="tl-content"><div class="tl-meta"><span class="tl-stage">${esc(meta.zh)} ${esc(meta.en)}</span><time class="tl-time">${esc(fmtClock(ev.t))}</time></div>${ev.msg ? `<p class="tl-msg">${esc(ev.msg)}</p>` : ''}${extra}</div></li>`;
}
function compareTrayHtml() { return '<div id="compare-tray" class="compare-tray" aria-live="polite">选择 2-5 家加入 Compare。</div>'; }
function refreshCompareTray(scope) { const picks = $$('[data-compare-place][aria-pressed="true"]', scope).map((b) => b.dataset.placeName); const tray = $('#compare-tray', scope); if (tray) tray.innerHTML = picks.length ? `<span>Compare ${picks.length}/5</span>${picks.map((n) => `<span class="chip">${esc(n)}</span>`).join('')}` : '选择 2-5 家加入 Compare。'; }
function toggleCompare(btn) { const scope = btn.closest('.job-results') || document, on = btn.getAttribute('aria-pressed') !== 'true'; if (on && $$('[data-compare-place][aria-pressed="true"]', scope).length >= 5) return; btn.setAttribute('aria-pressed', String(on)); btn.textContent = on ? '已加入' : '加入对比'; refreshCompareTray(scope); }
function renderReportArticle(rep) {
  const mdHasTitle = /^#\s/.test(String(rep.md ?? '')); // avoid doubling the serif title
  return `<article class="report">
    <header class="report-head">
      <span class="report-label">深挖报告 report</span>
      ${mdHasTitle ? '' : `<h3 class="report-name">${esc(rep.name)}</h3>`}
    </header>
    <div class="report-body">${mdToHtml(rep.md)}</div>
  </article>`;
}
function renderResult(result) {
  if (!result) return emptyHtml('任务完成但没有返回结果。');
  const places = result.places || [];
  const reports = result.reports || [];
  const errors = result.errors || [];
  const deepIds = new Set(reports.map((r) => r.place_id));
  const cut = (result.filtered || []).filter((v) => !v.relevant);
  const parts = [];
  parts.push(`<p class="result-summary">找到 <strong>${places.length}</strong> 家 · 深挖 <strong>${reports.length}</strong> 份报告${
    errors.length ? ` · <span class="warn">${errors.length} 个警告</span>` : ''}</p>`);
  if (result.plan) parts.push(renderPlanCard(result.plan));
  if (places.length) {
    parts.push(compareTrayHtml());
    parts.push(`<div class="place-list">${places.map((p) => `<div class="place-pick"><button type="button" class="place-row${deepIds.has(p.place_id) ? ' is-deep' : ''}" data-open-place="${esc(p.place_id)}">
      <span class="place-rating">${esc(stars(p.rating))}</span>
      <span class="place-name">${esc(p.name)}</span>
      <span class="place-count">${fmtInt(p.review_count)} 评价${deepIds.has(p.place_id) ? ' · 已深挖' : ''}</span>
      ${p.address ? `<span class="place-addr">${esc(p.address)}</span>` : ''}
    </button><button type="button" class="btn-ghost compare-pick" data-compare-place="${esc(p.place_id)}" data-place-name="${esc(p.name)}" aria-pressed="false">加入对比</button></div>`).join('')}</div>`);
  } else {
    parts.push(emptyHtml('一家都没找到 — 换个说法，或在「在哪里」里写明城市。'));
  }
  if (cut.length) {
    parts.push(`<details class="result-cut"><summary>AI 排除了 ${cut.length} 家（为什么）</summary>${renderVerdicts(result.filtered)}</details>`);
  }
  parts.push(reports.map(renderReportArticle).join(''));
  if (errors.length) {
    parts.push(`<details class="result-errors" open><summary>警告 ${errors.length}</summary><ul>${
      errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></details>`);
  }
  return parts.join('');
}
function renderShopCard(p, featured) {
  const rep = reportKey(p), picked = state.libraryCompare.includes(p.place_id), latest = p.latest_report_at ? `最近报告 ${relTime(p.latest_report_at)}${rep ? ` · ${rep}` : ''}` : '';
  return `<article class="shop-card${featured ? ' is-featured' : ''}"><div class="shop-card-top"><span class="shop-rating">${esc(stars(p.rating))}</span>${p.activity_risk ? `<span class="badge badge-risk">${esc(p.activity_risk.severity === 'high' ? '低活跃风险' : '近期偏静')}</span>` : ''}${p.report_count ? `<span class="badge">报告 ×${fmtInt(p.report_count)}</span>` : ''}</div>
    <h3 class="shop-name">${esc(p.name)}</h3>${p.category ? `<p class="shop-cat">${esc(p.category)}</p>` : ''}<p class="shop-stats"><span>${fmtInt(p.review_count)} 条在列</span><span>${fmtInt(p.cached_reviews)} 条已缓存</span></p>${p.address ? `<p class="shop-addr">${esc(p.address)}</p>` : ''}
    <p class="shop-fresh">更新于 ${esc(relTime(p.last_refreshed))}</p>${latest ? `<p class="shop-fresh">${esc(latest)}</p>` : ''}
    <div><button type="button" class="btn-ghost" data-favorite-place="${esc(p.place_id)}" aria-pressed="${p.favorite ? 'true' : 'false'}">${p.favorite ? '已收藏' : '收藏'}</button> <button type="button" class="btn-ghost" data-library-compare="${esc(p.place_id)}" aria-pressed="${picked ? 'true' : 'false'}">${picked ? '已对比' : '对比'}</button> <button type="button" class="btn-ghost" data-open-place="${esc(p.place_id)}">打开档案</button></div></article>`;
}
function placeScore(p) { const age = Math.max(0, Date.now() / 1000 - (p.last_refreshed || 0)); return (p.report_count || 0) * 650 + (p.cached_reviews || 0) * 2 + (p.review_count || 0) * 0.02 + (Number(p.rating) || 0) * 25 + Math.max(0, 80 - age / 3600) - (p.activity_risk ? 80 : 0); }
const filterVal = (id) => $(`#${id}`)?.value || '', reportKey = (p) => String(p.latest_report_profile || p.report_profile || '').trim(), isStale = (p) => Boolean(p.activity_risk) || Date.now() / 1000 - (p.last_refreshed || 0) > 14 * 86400;
function placeLangs(p) { return [p.languages, p.language_cohorts, p.review_languages, p.language_mix].flatMap((v) => Array.isArray(v) ? v : v ? [v] : []).map((x) => String((typeof x === 'object' ? x.lang || x.code || x.language || x.locale : x) || 'other').toLowerCase().slice(0, 2)).map((v) => ['zh', 'en', 'vi', 'ko'].includes(v) ? v : 'other'); }
function setSelectOptions(id, items, label) { const el = $(`#${id}`); if (!el) return; const old = el.value, names = { 'with-report': '有报告', 'no-report': '无报告' }, vals = [...new Set(items.filter(Boolean).map(String).sort())]; el.innerHTML = `<option value="">${esc(label)}</option>${vals.map((v) => `<option value="${esc(v)}">${esc(names[v] || v)}</option>`).join('')}`; el.value = vals.includes(old) ? old : ''; }
function syncLibraryControls() { setSelectOptions('library-category', state.places.map((p) => p.category), '全部类别 category'); setSelectOptions('library-report', ['with-report', 'no-report'].concat(state.places.map(reportKey)), '全部报告 profile'); }
function libraryMatches() { const q = ($('#library-search')?.value || '').trim().toLowerCase(), sort = filterVal('library-sort') || 'smart', cat = filterVal('library-category'), fresh = filterVal('library-freshness'), risk = filterVal('library-risk'), lang = filterVal('library-language'), cached = Number(filterVal('library-cached') || 0), rep = filterVal('library-report'); return state.places.filter((p) => (!q || [p.name, p.category, p.address, reportKey(p)].join(' ').toLowerCase().includes(q)) && (!cat || p.category === cat) && (!fresh || (fresh === 'stale' ? isStale(p) : !isStale(p))) && (!risk || (risk === 'risk' ? p.activity_risk : !p.activity_risk)) && (!lang || placeLangs(p).includes(lang)) && (!cached || (p.cached_reviews || 0) >= cached) && (!rep || (rep === 'with-report' ? (p.report_count || 0) > 0 : rep === 'no-report' ? !(p.report_count || 0) : reportKey(p) === rep))).sort((a, b) => sort === 'fresh' ? (b.last_refreshed || 0) - (a.last_refreshed || 0) : sort === 'cached' ? (b.cached_reviews || 0) - (a.cached_reviews || 0) : sort === 'rating' ? (Number(b.rating) || 0) - (Number(a.rating) || 0) : placeScore(b) - placeScore(a)); }
function renderLibraryGrid(places) { places = places || []; const featuredCount = places.length >= 5 ? 2 : places.length >= 3 ? 1 : 0; return places.map((p, i) => renderShopCard(p, i < featuredCount)).join(''); }
function renderLibraryCompare() { const box = $('#library-compare'); if (!box) return; const picks = state.libraryCompare.map((id) => state.places.find((p) => p.place_id === id)).filter(Boolean); box.innerHTML = picks.length ? `<div class="compare-tray"><span>Compare ${picks.length}/5</span>${picks.map((p) => `<button type="button" class="chip chip-link" data-open-place="${esc(p.place_id)}">${esc(p.name)} · ${esc(stars(p.rating))} · ${fmtInt(p.cached_reviews)}缓存</button>`).join('')}<button type="button" class="btn-ghost" data-library-compare-clear>清空</button></div>` : '<div class="compare-tray">选择 2-5 家加入 Compare。</div>'; }
function toggleLibraryCompare(btn) { const id = btn.dataset.libraryCompare; let xs = state.libraryCompare.filter((x) => x !== id); if (xs.length === state.libraryCompare.length) { if (xs.length >= 5) return; xs.push(id); } state.libraryCompare = xs; renderLibrary(); }
function renderLibrary() {
  const grid = $('#library-grid'), status = $('#library-status'); if (!grid || !status) return;
  if (!state.places.length) { state.libraryCompare = []; grid.innerHTML = ''; status.innerHTML = emptyHtml('资料库是空的 — 去「侦察」跑第一票。', 'scout'); renderLibraryCompare(); return; }
  const xs = libraryMatches(), limit = state.libraryLimit || LIBRARY_PAGE_SIZE, shown = xs.slice(0, limit), q = ($('#library-search')?.value || '').trim();
  grid.innerHTML = renderLibraryGrid(shown) + (xs.length > limit ? `<button type="button" class="btn-ghost library-more" data-library-more="1">显示更多 ${xs.length - limit} 家</button>` : '');
  status.innerHTML = xs.length ? `<p class="library-count">显示 ${shown.length} / ${state.places.length}${q ? ` · 搜索 ${esc(q)}` : ''}</p>` : emptyHtml('没有匹配的店 — 换个关键词。');
  renderLibraryCompare();
}
function renderSearchRow(s) {
  const places = s.places || [];
  const cutCount = places.filter((p) => p.relevant === false).length;
  const kept = places.filter((p) => p.relevant !== false);
  const more = kept.length > SEARCH_ROW_CHIP_LIMIT ? `<span class="chip chip-more">+${kept.length - SEARCH_ROW_CHIP_LIMIT} 家</span>` : '';
  const chips = kept.slice(0, SEARCH_ROW_CHIP_LIMIT)
    .map((p) => `<button type="button" class="chip chip-link" data-open-place="${esc(p.place_id)}">${esc(p.name)}</button>`)
    .join('') + more;
  return `<li class="search-row">
    <div class="search-main">
      <span class="search-query">${esc(s.query)}</span>
      ${s.location ? `<span class="search-loc">@ ${esc(s.location)}</span>` : ''}
      <span class="search-meta">${esc([s.source, cutCount ? `AI 排除 ${cutCount} 家` : '', relTime(s.created_at)].filter(Boolean).join(' · '))}</span>
    </div>
    ${chips ? `<div class="search-places">${chips}</div>` : ''}
  </li>`;
}
function renderHours(hoursJson) {
  if (!hoursJson) return '';
  let h = hoursJson;
  if (typeof h === 'string') {
    try { h = JSON.parse(h); } catch { return esc(hoursJson); }
  }
  if (Array.isArray(h)) return h.map((x) => esc(String(x))).join('<br>');
  if (h && typeof h === 'object') {
    return Object.entries(h).map(([k, v]) => `${esc(k)} — ${esc(String(v))}`).join('<br>');
  }
  return esc(String(hoursJson));
}
const LANG_META = { zh: ['中文', 'Chinese', 'Vec native / Chinese readers'], en: ['English', 'EN', 'Global travelers'], vi: ['Tiếng Việt', 'Vietnamese', 'Local Vietnamese voices'], ko: ['한국어', 'Korean', 'Korean visitors'], ja: ['日本語', 'Japanese', 'Japanese visitors'], th: ['ไทย', 'Thai', 'Thai visitors'], other: ['其他语言', 'Other', 'Mixed language'], unknown: ['无文字', 'No text', 'Rating-only'] };
const LANG_ORDER = ['zh', 'en', 'vi', 'ko', 'ja', 'th', 'other', 'unknown'], RATING_FILTERS = [['all', '全部评分', 'All'], ['5', '5★', 'great'], ['4', '4★', 'ok'], ['low', '≤3★', '问题']];
const VI_RE = /[ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]|\b(và|không|nhưng|đẹp|đường|người|nên|khó|rất|chơi|biển|rác|nước|nơi|này|cửa hàng|phục vụ|chất lượng)\b/i;
const THEME_RULES = [['price', '价格', 'price', /价格|价钱|公道|押金|贵|便宜|price|cost|cheap|expensive|deposit|phí|giá|tiền/i], ['service', '服务/态度', 'service', /服务|老板|态度|helpful|friendly|owner|staff|service|phục vụ|nhân viên|chủ|친절/i], ['quality', '质量/效果', 'quality', /质量|品质|效果|好用|guitar|instrument|quality|selection|đàn|chất lượng|악기/i], ['access', '到达/停车', 'access', /停车|到达|难找|滑|parking|road|access|enter|đường|vào|khó|trượt|leo|주차/i], ['repair', '维修/调琴', 'repair', /修|维修|调琴|调整|repair|setup|action|eq|fix|lắp|chỉnh/i], ['rental', '租赁', 'rental', /租|租赁|rental|rent|hire|thuê/i], ['availability', '选择/库存', 'availability', /选择|库存|现货|available|selection|stock|nhiều|lựa chọn/i], ['crowd', '人流/安静', 'crowd', /人多|排队|拥挤|安静|crowd|busy|quiet|overcrowded|đông|ồn ào/i], ['clean', '清洁/垃圾', 'cleanliness', /干净|垃圾|塑料|clean|trash|plastic|rác|chai nhựa/i], ['view', '景色/氛围', 'view', /漂亮|景色|氛围|view|beautiful|gorgeous|serene|đẹp|trong xanh|mát/i], ['food', '饮食', 'food/drink', /咖啡|椰子|吃|drink|coffee|coconut|food|cafe|nước/i]];
function langMeta(code) { return LANG_META[code] || LANG_META.other; }
function reviewBody(r) { return [r.text, r.owner_response].filter(Boolean).join(' '); }
function detectReviewLang(text) {
  const s = String(text || '').trim();
  if (!s) return 'unknown';
  const hit = [[/[\u3400-\u9fff]/, 'zh'], [/[\uac00-\ud7af]/, 'ko'], [/[\u3040-\u30ff]/, 'ja'], [/[\u0e00-\u0e7f]/, 'th'], [VI_RE, 'vi']].find(([re]) => re.test(s));
  if (hit) return hit[1];
  return /[a-z]/i.test(s) ? 'en' : 'other';
}
function reviewThemes(text) { const hits = THEME_RULES.filter((t) => t[3].test(text)).slice(0, 3); return hits.length ? hits : [['general', '整体体验', 'general']]; }
function reviewRatingBand(rating) { const n = Number(rating); return Number.isFinite(n) && n > 0 ? (n >= 4.5 ? '5' : n >= 3.5 ? '4' : 'low') : 'none'; }
function languageGroups(reviews) {
  const groups = new Map();
  for (const r of reviews) {
    const body = reviewBody(r);
    const code = detectReviewLang(body);
    const g = groups.get(code) || { code, count: 0, sum: 0, themes: new Map(), sample: '' };
    g.count += 1; g.sum += Number(r.rating) || 0;
    if (!g.sample && body) g.sample = body.length > 120 ? `${body.slice(0, 120)}…` : body;
    for (const t of reviewThemes(body)) g.themes.set(t[0], { row: t, count: (g.themes.get(t[0])?.count || 0) + 1 });
    groups.set(code, g);
  }
  return Array.from(groups.values()).sort((a, b) => (LANG_ORDER.indexOf(a.code) - LANG_ORDER.indexOf(b.code)) || (b.count - a.count));
}
function renderLanguageLens(reviews) {
  if (!reviews.length) return '';
  const groups = languageGroups(reviews);
  const filters = ['all', ...groups.map((g) => g.code)].map((code) => { const m = code === 'all' ? ['全部', 'All'] : langMeta(code); return `<button type="button" class="lang-filter${code === 'all' ? ' is-active' : ''}" data-review-lang-filter="${esc(code)}" aria-pressed="${code === 'all'}">${esc(m[0])}<span>${esc(m[1])}</span></button>`; }).join('');
  const ratingCounts = reviews.reduce((m, r) => { const k = reviewRatingBand(r.rating); m[k] = (m[k] || 0) + 1; return m; }, { all: reviews.length });
  const ratingFilters = RATING_FILTERS.map(([code, zh, en]) => `<button type="button" class="rating-filter${code === 'all' ? ' is-active' : ''}" data-review-rating-filter="${esc(code)}" aria-pressed="${code === 'all'}">${esc(zh)}<span>${esc(en)} · ${ratingCounts[code] || 0}</span></button>`).join('');
  const cards = groups.slice(0, 6).map((g) => {
    const m = langMeta(g.code), avg = g.count ? (g.sum / g.count).toFixed(1) : '—';
    const themes = Array.from(g.themes.values()).sort((a, b) => b.count - a.count).slice(0, 4).map((x) => `<span>${esc(x.row[1])}<small>${esc(x.row[2])} · ${x.count}</small></span>`).join('');
    return `<article class="language-card" data-review-lang-card="${esc(g.code)}"><h4>${esc(m[0])} <span>${esc(m[1])}</span></h4><p>${g.count} 条 · ★ ${avg} · ${esc(m[2])}</p><div class="language-themes">${themes}</div>${g.sample ? `<blockquote>${esc(g.sample)}</blockquote>` : ''}</article>`;
  }).join('');
  const target = `<label class="translation-target-wrap">译成 <select class="translation-target" aria-label="译文目标语言"><option value="zh"${state.translationTarget === 'zh' ? ' selected' : ''}>中文 CN</option><option value="en"${state.translationTarget === 'en' ? ' selected' : ''}>English</option></select></label>`;
  return `<section class="language-lens" aria-label="review language lens"><div class="language-lens-head"><div><h3>语言视角 <span>language lens</span></h3><p>language tab 保留给读原文；细分洞察可展开。</p></div><div class="language-actions">${target}<p class="review-filter-count" aria-live="polite">显示全部 ${reviews.length}</p></div></div><div class="language-filters">${filters}</div><div class="rating-filters">${ratingFilters}</div><details class="language-insights"><summary>展开语言洞察 <span>insight cards · ${groups.length}</span></summary><div class="language-grid">${cards}</div></details></section>`;
}
function renderReviewCard(r) {
  const lang = detectReviewLang(reviewBody(r));
  const dateStr = typeof r.review_date === 'number' ? relTime(r.review_date) : (r.review_date || '');
  const m = langMeta(lang);
  const target = state.translationTarget;
  const tx = r.review_id && r.text ? `<button type="button" class="review-translate" data-review-translate="${esc(r.review_id)}" data-review-translate-target="${target}">译文 ${txLabel(target)}</button>` : '';
  return `<article class="review" data-review-lang="${esc(lang)}" data-review-rating="${esc(reviewRatingBand(r.rating))}"><header class="review-meta">
      <span class="review-stars">${esc(stars(r.rating))}</span><span class="review-author">${esc(r.author || '匿名')}</span><span class="review-lang">${esc(m[0])}</span>${dateStr ? `<span class="review-date">${esc(dateStr)}</span>` : ''}${tx}</header>
    ${r.text ? `<p class="review-text">${esc(r.text)}</p>` : ''}
    ${r.owner_response ? `<div class="owner-reply"><span class="owner-label">店家回复</span><p>${esc(r.owner_response)}</p></div>` : ''}
  </article>`;
}
function renderDetail(data) {
  const p = (data && data.place) || {};
  const reviews = (data && data.reviews) || [];
  const rep = (data && data.report) || null;
  const facts = [];
  const addFact = (label, html) => { if (html) facts.push(`<div class="fact"><dt>${label}</dt><dd>${html}</dd></div>`); };
  addFact('地址', p.address && esc(p.address));
  addFact('电话', p.phone && esc(p.phone));
  const site = safeUrl(p.website);
  addFact('网站', site && `<a href="${esc(site)}" target="_blank" rel="noopener noreferrer">${esc(site)}</a>`);
  addFact('营业时间', renderHours(p.hours_json));
  const maps = safeUrl(p.maps_url);
  addFact('地图', maps && `<a href="${esc(maps)}" target="_blank" rel="noopener noreferrer">Google Maps ↗</a>`);
  return `<header class="detail-shop">
    <p class="detail-kicker">${esc(p.category || '店铺')} · ${esc(stars(p.rating))} · ${fmtInt(p.review_count)} 条在列</p>
    <h2 class="detail-name">${esc(p.name || '未命名')}</h2>
    ${p.activity_risk ? `<p class="activity-risk">${esc(p.activity_risk.label)} · ${esc(p.activity_risk.reason)}</p>` : ''}
    <p class="detail-fresh">已缓存 ${reviews.length} 条评价 · 更新于 ${esc(relTime(p.last_refreshed))}
      <button type="button" class="btn-ghost btn-danger" data-delete-place="${esc(p.place_id)}" data-place-name="${esc(p.name || '')}">从缓存移除 ✕</button>
    </p>
    ${facts.length ? `<dl class="facts">${facts.join('')}</dl>` : ''}
  </header>
  <section class="detail-section">
    <form class="ask-shop-form" data-place-id="${esc(p.place_id)}">
      <label>只问这家店 <span class="label-en">ask this shop</span></label>
      <div class="ask-inline">
        <input type="text" class="ask-shop-input" autocomplete="off" placeholder="例：他们家能修琴吗？老板态度怎么样？…">
        <button type="submit" class="btn-small">问 →</button>
      </div>
    </form>
    <div class="qa-history" data-qa-scope="${esc(p.place_id)}"></div>
    <div class="ask-shop-answer"></div>
  </section>
  <section class="detail-section">
    ${rep
    ? `<div class="report-meta-line">最新报告${rep.profile ? ` · ${esc(rep.profile)}` : ''}${rep.model ? ` · <span class="model-tag">${esc(rep.model)}</span>` : ''} · ${esc(relTime(rep.created_at))}</div>
       <article class="report"><div class="report-body">${mdToHtml(rep.md)}</div></article>`
    : '<div class="empty small">这家店还没有报告 — 去「单店」跑一份深挖。</div>'}
  </section>
  <details class="detail-reviews">
    <summary>评价原文 reviews · ${reviews.length} 条</summary>
    ${renderLanguageLens(reviews)}
    <div class="review-list">${reviews.map(renderReviewCard).join('')}</div>
  </details>`;
}
const jobEls = (kind) => ({ wrap: $(`#${kind}-job`), timeline: $(`#${kind}-timeline`), results: $(`#${kind}-results`), submit: $(`#${kind}-submit`), jobid: $(`#${kind}-jobid`) });
function setLiveMsg(kind, msg) { const el = $(`#${kind}-live .tl-msg`); if (el) el.textContent = msg; }
function removeLive(kind) { const el = $(`#${kind}-live`); if (el) el.remove(); }
function appendEvents(kind, events) {
  const job = state.jobs[kind];
  if (!job || !Array.isArray(events) || !events.length) return;
  const fresh = events.filter((ev, i) => ev.id == null ? i >= job.rendered : Number(ev.id) > job.lastEventId);
  if (!fresh.length) return;
  const els = jobEls(kind);
  const html = fresh.map(renderEvent).join('');
  job.rendered = Math.max(job.rendered, events.length);
  job.lastEventId = Math.max(job.lastEventId, ...fresh.map((ev) => Number(ev.id) || 0));
  const live = $(`#${kind}-live`);
  if (live) live.insertAdjacentHTML('beforebegin', html);
  else els.timeline.insertAdjacentHTML('beforeend', html);
  els.timeline.scrollTop = els.timeline.scrollHeight; // auto-scroll timeline only
}
function failJob(kind, msg) {
  const job = state.jobs[kind];
  if (job) { job.active = false; if (job.es) job.es.close(); }
  const els = jobEls(kind);
  els.submit.disabled = false;
  removeLive(kind);
  els.results.innerHTML = errorHtml(msg);
}
async function startJob(kind, path, body) {
  const prev = state.jobs[kind];
  if (prev && prev.timer) clearTimeout(prev.timer);
  if (prev && prev.es) prev.es.close();
  if (prev) prev.active = false;
  const job = { id: null, path, body, rendered: 0, lastEventId: 0, fails: 0, timer: null, es: null, active: true };
  state.jobs[kind] = job;
  const els = jobEls(kind);
  els.submit.disabled = true;
  els.wrap.hidden = false;
  els.results.innerHTML = '';
  els.jobid.textContent = '';
  els.timeline.innerHTML = `<li class="tl-item tl-live" id="${kind}-live">
    <span class="tl-dot dot-live"></span>
    <div class="tl-content"><p class="tl-msg muted">已提交，等待后端响应…</p></div>
  </li>`;
  try {
    const { job_id } = await apiPost(path, body);
    if (state.jobs[kind] !== job || !job.active) return;
    job.id = job_id;
    els.jobid.textContent = `job ${job_id}`;
    streamJob(kind);
  } catch (err) {
    failJob(kind, `提交失败：${err.message} — 确认后端在运行后重试。`);
  }
}
function streamJob(kind) {
  const job = state.jobs[kind]; if (!window.EventSource || !job?.id) return pollJob(kind);
  const es = new EventSource(`/api/jobs/${encodeURIComponent(job.id)}/events?after=${job.lastEventId || 0}`); job.es = es;
  es.onmessage = (e) => { if (state.jobs[kind] !== job || !job.active) return es.close(); try { const ev = JSON.parse(e.data); appendEvents(kind, [ev]); if (ev.stage === 'done') { es.close(); pollJob(kind); } } catch { /* bad SSE frame falls through to final poll */ } };
  es.onerror = () => { es.close(); if (state.jobs[kind] === job && job.active) pollJob(kind); };
}
async function pollJob(kind) {
  const job = state.jobs[kind];
  if (!job || !job.active) return;
  let data;
  try {
    data = await apiGet(`/api/jobs/${encodeURIComponent(job.id)}`);
    job.fails = 0;
  } catch (err) {
    job.fails += 1;
    if (job.fails >= MAX_POLL_FAILS) {
      failJob(kind, `轮询失败：${err.message} — 后端可能掉线了。修好后重新提交即可，已完成的步骤有缓存，几乎不花时间。`);
      return;
    }
    setLiveMsg(kind, `轮询失败，重试中（${job.fails}/${MAX_POLL_FAILS}）…`);
    job.timer = setTimeout(() => pollJob(kind), POLL_MS);
    return;
  }
  appendEvents(kind, data.events || []);
  if (data.status === 'running') {
    setLiveMsg(kind, '运行中…');
    job.timer = setTimeout(() => pollJob(kind), POLL_MS);
    return;
  }
  job.active = false;
  const els = jobEls(kind);
  els.submit.disabled = false;
  if (job.es) job.es.close();
  removeLive(kind);
  if (data.status === 'error') {
    els.results.innerHTML = errorHtml(`任务失败：${data.error || '未知错误'} — 可直接重新提交，已完成的步骤会命中缓存。`);
    return;
  }
  if (data.status === 'interrupted') { els.results.innerHTML = `<div class="error-box"><span class="error-label">中断 interrupted</span>${esc(`任务中断：${data.retry_hint || data.error || '后端重启，中止了这个任务。'}`)}<button type="button" class="btn-ghost" data-retry-job="${esc(kind)}">用缓存重试 →</button></div>`; return; }
  els.results.innerHTML = renderResult(data.result);
  if (kind === 'scout') loadScoutPast();
  if (state.libraryLoaded) loadLibrary(); // keep library tab fresh in background
}
async function loadScoutPast() {
  const list = $('#scout-past-list'), status = $('#scout-past-status'); if (!list || !status) return;
  if (!list.innerHTML) status.innerHTML = loadingHtml('读取过去侦察');
  try { state.searches = await apiGet('/api/searches') || []; list.innerHTML = state.searches.slice(0, 8).map(renderSearchRow).join(''); status.innerHTML = state.searches.length ? '' : emptyHtml('还没有过去侦察。'); refreshCommandMode(); }
  catch (err) { list.innerHTML = ''; status.innerHTML = errorHtml(`读取过去侦察失败：${err.message}`); }
}
async function loadLibrary() {
  const grid = $('#library-grid'), status = $('#library-status'), hList = $('#history-list'), hStatus = $('#history-status');
  if (!grid.innerHTML) status.innerHTML = loadingHtml('读取资料库');
  const [placesR, searchesR] = await Promise.allSettled([apiGet('/api/places'), apiGet('/api/searches')]);
  if (placesR.status === 'fulfilled') {
    state.places = placesR.value || [];
    syncLibraryControls();
    renderLibrary();
  } else {
    grid.innerHTML = '';
    status.innerHTML = errorHtml(`读取资料库失败：${placesR.reason.message}`);
  }
  if (searchesR.status === 'fulfilled') {
    state.searches = searchesR.value || [];
    hList.innerHTML = state.searches.map(renderSearchRow).join('');
    hStatus.innerHTML = state.searches.length ? '' : emptyHtml('还没有搜索记录。');
  } else {
    hList.innerHTML = '';
    hStatus.innerHTML = errorHtml(`读取历史失败：${searchesR.reason.message}`);
  }
}
async function toggleFavorite(btn) { const id = btn.dataset.favoritePlace, next = btn.getAttribute('aria-pressed') !== 'true'; btn.disabled = true; try { await apiPost(`/api/places/${encodeURIComponent(id)}/favorite`, { favorite: next }); await loadLibrary(); } catch (err) { window.alert(`收藏失败：${err.message}`); } finally { btn.disabled = false; } }
async function openDetail(placeId) {
  const overlay = $('#detail-overlay');
  const body = $('#detail-body');
  const close = $('#detail-close');
  if (overlay.hidden) state.detailReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  overlay.hidden = false;
  document.body.classList.add('no-scroll');
  body.innerHTML = loadingHtml('读取店铺档案');
  close.focus({ preventScroll: true });
  try {
    const data = await apiGet(`/api/places/${encodeURIComponent(placeId)}`);
    state.detail = data;
    body.innerHTML = renderDetail(data);
    body.scrollTop = 0;
    loadQaHistory(placeId); // past Q&A for this shop, re-askable
  } catch (err) {
    body.innerHTML = errorHtml(`读取失败：${err.message}`);
  }
}
function closeDetail() {
  $('#detail-overlay').hidden = true;
  document.body.classList.remove('no-scroll');
  state.detail = null;
  const returnFocus = state.detailReturnFocus;
  state.detailReturnFocus = null;
  if (returnFocus && document.contains(returnFocus)) returnFocus.focus({ preventScroll: true });
}
function trapDetailFocus(e) {
  const panel = $('.detail-panel');
  const xs = $$('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])', panel).filter((x) => x.offsetParent !== null || x === document.activeElement);
  if (!xs.length) return;
  const first = xs[0], last = xs[xs.length - 1], active = document.activeElement;
  if (e.shiftKey && (!panel.contains(active) || active === first)) { e.preventDefault(); return last.focus({ preventScroll: true }); }
  if (!e.shiftKey && active === last) { e.preventDefault(); first.focus({ preventScroll: true }); }
}
function switchTab(name, syncHash = true) {
  if (!TAB_NAMES.includes(name)) name = 'scout';
  state.tab = name;
  $$('.tab').forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle('is-active', on);
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
  });
  $$('.panel').forEach((p) => { const on = p.id === `panel-${name}`; p.hidden = !on; p.tabIndex = on ? 0 : -1; });
  if (syncHash && location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
  if (name === 'scout') loadScoutPast();
  if (name === 'library') {
    state.libraryLoaded = true;
    loadLibrary();
  }
  if (name === 'ask') {
    $('#ask-question').focus();
    loadQaHistory(null);
  }
}
function flashInvalid(el) { el.classList.add('is-invalid'); el.focus(); setTimeout(() => el.classList.remove('is-invalid'), 1200); }
function submitOnEnter(textarea, form) { textarea.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } }); }
function bindForms() {
  const scoutForm = $('#scout-form');
  scoutForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const query = $('#scout-query').value.trim();
    if (!query) return flashInvalid($('#scout-query'));
    const body = { query, top: clampInt($('#scout-top').value, 1, 8, 3), max_reviews: clampInt($('#scout-maxr').value, 20, 5000, 300) };
    const near = $('#scout-near').value.trim();
    if (state.commandMode === 'ask') { switchTab('ask'); $('#ask-question').value = query; return runAsk(query, null, $('#ask-answer'), false); }
    if (state.commandMode === 'shop') {
      const shopBody = { target: query, max_reviews: body.max_reviews };
      if (near) { shopBody.near = near; $('#shop-near').value = near; } if ($('#scout-profile').value) shopBody.profile = $('#scout-profile').value; if ($('#scout-refresh').checked) shopBody.refresh = true;
      $('#shop-target').value = query; switchTab('shop'); return startJob('shop', '/api/shop', shopBody);
    }
    const cached = matchingScout(query, near);
    if (cached && !$('#scout-refresh').checked) { $('#scout-past-status').textContent = '命中缓存：下面已有同一侦察；强制刷新才会重新抓取。'; return $('#scout-past').scrollIntoView({ block: 'start', behavior: 'smooth' }); }
    if (near) body.near = near;
    if ($('#scout-profile').value) body.profile = $('#scout-profile').value;
    if ($('#scout-refresh').checked) body.refresh = true;
    if ($('#scout-noai').checked) body.no_ai = true;
    startJob('scout', '/api/scout', body);
  });
  $('#scout-query').addEventListener('input', refreshCommandMode); $$('[data-command-mode]').forEach((btn) => btn.addEventListener('click', () => setCommandMode(btn.dataset.commandMode, true))); refreshCommandMode(); submitOnEnter($('#scout-query'), scoutForm);
  $('#shop-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const target = $('#shop-target').value.trim();
    if (!target) return flashInvalid($('#shop-target'));
    const body = {
      target,
      max_reviews: clampInt($('#shop-maxr').value, 20, 5000, 300),
    };
    const near = $('#shop-near').value.trim();
    if (near) body.near = near;
    if ($('#shop-profile').value) body.profile = $('#shop-profile').value;
    if ($('#shop-refresh').checked) body.refresh = true;
    startJob('shop', '/api/shop', body);
  });
  const askForm = $('#ask-form');
  askForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const q = $('#ask-question').value.trim();
    if (!q) return flashInvalid($('#ask-question'));
    runAsk(q, null, $('#ask-answer'), false);
  });
  submitOnEnter($('#ask-question'), askForm);
  // scoped ask inside the detail overlay (markup is rendered, so delegate)
  $('#detail-body').addEventListener('submit', (e) => {
    const form = e.target.closest('.ask-shop-form');
    if (!form) return;
    e.preventDefault();
    const input = form.querySelector('.ask-shop-input');
    const out = form.parentElement.querySelector('.ask-shop-answer');
    const q = input.value.trim();
    if (!q) return flashInvalid(input);
    runAsk(q, form.dataset.placeId, out, false);
  });
}
function renderAnswer(res, q, placeId) {
  const cachedNote = res.cached
    ? `<div class="answer-cached">⚡ 缓存答案 · 来自 ${esc(relTime(res.created_at))}的相同问题
        <button type="button" class="btn-ghost btn-refresh" data-refresh-q="${esc(q)}"
          data-refresh-place="${esc(placeId || '')}">重新推理 ↻</button></div>`
    : '';
  const modelTag = res.model
    ? `<span class="model-tag">${esc(res.model)}${res.provider ? ` @ ${esc(res.provider)}` : ''}</span>`
    : '';
  return `<div class="answer"><div class="answer-label">回答 answer ${modelTag}</div>${cachedNote}
    <div class="report-body">${mdToHtml(res.answer)}</div></div>`;
}
async function runAsk(q, placeId, out, fresh) {
  const submit = $('#ask-submit');
  if (!placeId && submit) submit.disabled = true;
  out.innerHTML = loadingHtml(fresh ? '强制重新推理中'
    : placeId ? '只检索这家店的评价 + 推理中' : '在整个缓存里检索 + 推理中');
  try {
    const body = { question: q };
    if (placeId) body.place_id = placeId;
    if (fresh) body.fresh = true;
    const res = await apiPost('/api/ask', body);
    out.innerHTML = renderAnswer(res, q, placeId);
    loadQaHistory(placeId || null);
  } catch (err) {
    out.innerHTML = errorHtml(`提问失败：${err.message}${placeId ? '' : '（缓存是空的？先去侦察。）'}`);
  } finally {
    if (!placeId && submit) submit.disabled = false;
  }
}
function renderQaChips(rows) {
  if (!rows || !rows.length) return '';
  const chips = rows.map((r) => {
    const label = r.question.length > 42 ? `${r.question.slice(0, 42)}…` : r.question;
    const place = r.place_id ? (r.place_name || '单店') : '';
    return `<button type="button" class="chip chip-link" data-ask-again="${esc(r.question)}"
      ${place ? `data-ask-place="${esc(r.place_id)}"` : ''}
      title="${esc(place ? `${place} · ` : '')}${esc(relTime(r.created_at))} · 点击重问（命中缓存则免费秒回）">${esc(label)}${place ? ` · ${esc(place)}` : ''}</button>`;
  }).join('');
  return `<div class="qa-chips"><span class="qa-chips-label">问过 asked</span>${chips}</div>`;
}
async function loadQaHistory(placeId) {
  const target = placeId
    ? $(`.qa-history[data-qa-scope="${CSS.escape(placeId)}"]`)
    : $('#ask-history');
  if (!target) return;
  try {
    const rows = await apiGet(placeId ? `/api/qa?place_id=${encodeURIComponent(placeId)}` : '/api/qa?scope=all');
    target.innerHTML = renderQaChips(rows);
  } catch { /* history is optional decoration */ }
}

function bindGlobal() {
  document.addEventListener('click', (e) => {
    const tab = e.target.closest('[data-tab]');
    if (tab) return switchTab(tab.dataset.tab);
    const goto = e.target.closest('[data-goto]');
    if (goto) return switchTab(goto.dataset.goto);
    const retry = e.target.closest('[data-retry-job]'); if (retry) { const j = state.jobs[retry.dataset.retryJob]; if (j) return startJob(retry.dataset.retryJob, j.path, { ...j.body, refresh: false }); }
    const refresh = e.target.closest('[data-refresh-q]');
    if (refresh) {
      const out = refresh.closest('.answer').parentElement;
      return runAsk(refresh.dataset.refreshQ, refresh.dataset.refreshPlace || null, out, true);
    }
    const again = e.target.closest('[data-ask-again]');
    if (again) {
      const place = again.dataset.askPlace || null;
      const scope = again.closest('.qa-history');
      if (scope) { // scoped re-ask inside the dossier
        const out = scope.parentElement.querySelector('.ask-shop-answer');
        const input = scope.parentElement.querySelector('.ask-shop-input');
        if (input) input.value = again.dataset.askAgain;
        return runAsk(again.dataset.askAgain, place || scope.dataset.qaScope, out, false);
      }
      $('#ask-question').value = again.dataset.askAgain;
      return runAsk(again.dataset.askAgain, place, $('#ask-answer'), false);
    }
    const reviewFilter = e.target.closest('[data-review-lang-filter],[data-review-rating-filter]');
    if (reviewFilter) return filterReviewLanguage(reviewFilter);
    const tx = e.target.closest('[data-review-translate]');
    if (tx) return translateReview(tx);
    const fav = e.target.closest('[data-favorite-place]');
    if (fav) return toggleFavorite(fav);
    const cmp = e.target.closest('[data-compare-place]');
    if (cmp) return toggleCompare(cmp);
    if (e.target.closest('[data-library-compare-clear]')) { state.libraryCompare = []; return renderLibrary(); }
    const lcmp = e.target.closest('[data-library-compare]');
    if (lcmp) return toggleLibraryCompare(lcmp);
    const del = e.target.closest('[data-delete-place]');
    if (del) return deletePlace(del.dataset.deletePlace, del.dataset.placeName);
    const open = e.target.closest('[data-open-place]');
    if (open) return openDetail(open.dataset.openPlace);
    if (e.target.closest('[data-close]') || e.target.closest('#detail-close')) return closeDetail();
    if (e.target.closest('#scout-past-reload')) return loadScoutPast();
    if (e.target.closest('[data-library-more]')) { state.libraryLimit += LIBRARY_PAGE_SIZE; return renderLibrary(); }
    if (e.target.closest('#library-reload')) return loadLibrary();
    if (e.target.closest('#model-switch')) return toggleModelPicker();
    if (e.target.closest('#model-save')) return saveModel();
  });
  document.addEventListener('input', (e) => { if (e.target.closest('#library-search')) { state.libraryLimit = LIBRARY_PAGE_SIZE; renderLibrary(); } });
  document.addEventListener('change', (e) => { const sel = e.target.closest('.translation-target'); if (sel) setTranslationTarget(sel); if (e.target.closest(LIBRARY_FILTERS)) { state.libraryLimit = LIBRARY_PAGE_SIZE; renderLibrary(); } });
  $('#model-select').addEventListener('change', () => {
    $('#model-custom').hidden = $('#model-select').value !== CUSTOM_MODEL;
  });
  document.addEventListener('keydown', (e) => {
    const tab = e.target.closest('.tab');
    if (tab && ['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) {
      e.preventDefault();
      const i = TAB_NAMES.indexOf(tab.dataset.tab);
      const n = e.key === 'Home' ? 0 : e.key === 'End' ? TAB_NAMES.length - 1
        : e.key === 'ArrowRight' ? (i + 1) % TAB_NAMES.length : (i - 1 + TAB_NAMES.length) % TAB_NAMES.length;
      switchTab(TAB_NAMES[n]);
      $(`#tab-${TAB_NAMES[n]}`).focus();
      return;
    }
    if (e.key === 'Tab' && !$('#detail-overlay').hidden) trapDetailFocus(e);
    if (e.key === 'Escape' && !$('#detail-overlay').hidden) closeDetail();
  });
}
function filterReviewLanguage(btn) {
  const panel = btn.closest('.detail-reviews'); if (!panel) return;
  const selector = btn.dataset.reviewRatingFilter != null ? '[data-review-rating-filter]' : '[data-review-lang-filter]';
  $$(selector, panel).forEach((b) => { b.classList.toggle('is-active', b === btn); b.setAttribute('aria-pressed', String(b === btn)); });
  const code = $('[data-review-lang-filter].is-active', panel)?.dataset.reviewLangFilter || 'all', rating = $('[data-review-rating-filter].is-active', panel)?.dataset.reviewRatingFilter || 'all';
  const cards = $$('.review', panel);
  let shown = 0;
  for (const card of cards) {
    const keep = (code === 'all' || card.dataset.reviewLang === code) && (rating === 'all' || card.dataset.reviewRating === rating);
    card.hidden = !keep;
    if (keep) shown += 1;
  }
  const label = $('.review-filter-count', panel);
  if (label) label.textContent = code === 'all' && rating === 'all' ? `显示全部 ${cards.length}` : `显示 ${shown} / ${cards.length}`;
}
function setTranslationTarget(sel) {
  const panel = sel.closest('.detail-reviews'), target = ['zh', 'en'].includes(sel.value) ? sel.value : 'zh';
  if (panel) { panel.dataset.txBatch = String(Number(panel.dataset.txBatch || 0) + 1); delete panel.dataset.txBusy; }
  state.translationTarget = target; localStorage.setItem(TX_TARGET_KEY, target);
  $$('.translation-target', panel).forEach((x) => { x.value = target; }); $$('.review-translation', panel).forEach((x) => x.remove());
  $$('[data-review-translate]', panel).forEach((b) => { b.dataset.reviewTranslateTarget = target; b.textContent = `译文 ${txLabel(target)}`; b.disabled = false; });
}
function visibleTranslateButtons(btn) { const panel = btn.closest('.detail-reviews') || document; return $$('[data-review-translate]', panel).filter((b) => !b.closest('.review')?.hidden); }
async function translateOneReview(btn, token) {
  const panel = btn.closest('.detail-reviews');
  if (panel && panel.dataset.txBatch !== token) return;
  const card = btn.closest('.review'), target = btn.dataset.reviewTranslateTarget || state.translationTarget, label = `译文 ${txLabel(target)}`;
  $('.review-translation.is-error', card)?.remove();
  btn.disabled = true; btn.textContent = '翻译中…';
  try {
    const r = await apiPost('/api/reviews/translate', { review_id: btn.dataset.reviewTranslate, target_lang: target });
    if ((panel && panel.dataset.txBatch !== token) || (btn.dataset.reviewTranslateTarget || state.translationTarget) !== target) return;
    card.insertAdjacentHTML('beforeend', `<div class="review-translation"><span>译文 ${esc(r.target_lang)}${r.cached ? ' · cached' : ''}</span><p>${esc(r.text)}</p></div>`);
    btn.textContent = '已译';
  } catch (err) {
    if (panel && panel.dataset.txBatch !== token) return;
    card.insertAdjacentHTML('beforeend', `<div class="review-translation is-error">${esc(`翻译失败：${err.message}`)}</div>`);
    btn.textContent = label;
  } finally { btn.disabled = false; }
}
async function translateReview(btn) {
  const panel = btn.closest('.detail-reviews'); if (panel?.dataset.txBusy === '1') return;
  const buttons = visibleTranslateButtons(btn), pending = buttons.filter((b) => !$('.review-translation:not(.is-error)', b.closest('.review')));
  if (!pending.length) { buttons.forEach((b) => { const block = $('.review-translation', b.closest('.review')); if (block) { block.hidden = !block.hidden; b.textContent = block.hidden ? `译文 ${txLabel(b.dataset.reviewTranslateTarget || state.translationTarget)}` : '已译'; } }); return; }
  const token = String(Number(panel?.dataset.txBatch || 0) + 1); if (panel) { panel.dataset.txBatch = token; panel.dataset.txBusy = '1'; }
  const controls = panel ? [...buttons, ...$$('.translation-target', panel)] : buttons; controls.forEach((x) => { x.disabled = true; });
  let i = 0; try { await Promise.all(Array.from({ length: Math.min(3, pending.length) }, async () => { while (i < pending.length && (!panel || panel.dataset.txBatch === token)) await translateOneReview(pending[i++], token); })); }
  finally { if (!panel || panel.dataset.txBatch === token) { if (panel) delete panel.dataset.txBusy; controls.forEach((x) => { x.disabled = false; }); } }
}
async function deletePlace(placeId, name) {
  if (!window.confirm(`把「${name || placeId}」连同它缓存的评价、报告、问答一起移除？\n（下次搜到它会重新抓取）`)) return;
  try {
    await apiDelete(`/api/places/${encodeURIComponent(placeId)}`);
    closeDetail();
    loadLibrary();
  } catch (err) {
    window.alert(`删除失败：${err.message}`);
  }
}
async function loadProfiles() {
  try {
    const names = await apiGet('/api/profiles');
    state.profiles = names;
    for (const sel of [$('#scout-profile'), $('#shop-profile')]) {
      for (const n of names) sel.appendChild(new Option(n, n));
    }
  } catch { /* backend offline — selects keep "auto" only */ }
}
async function loadMeta() {
  try {
    const m = await apiGet('/api/meta');
    state.meta = m;
    const el = $('#meta-line');
    if (el && m.reason) {
      el.textContent = `推理 ${m.reason.model} @ ${m.reason.provider} · 译文 ${m.translate?.model || '?'} @ ${m.translate?.provider || '?'} · 向量 ${m.embed.model} @ ${m.embed.provider} · v${m.version}`;
      $('#model-switch').hidden = false;
    }
  } catch { /* backend offline — footer stays minimal */ }
}
const CUSTOM_MODEL = '__custom__';
async function toggleModelPicker() {
  const picker = $('#model-picker');
  if (!picker.hidden) { picker.hidden = true; return; }
  picker.hidden = false;
  const sel = $('#model-select'), status = $('#model-status');
  sel.innerHTML = '';
  status.textContent = '实时拉取提供商可用模型…';
  try {
    const res = await apiGet('/api/models');
    for (const name of res.models) sel.appendChild(new Option(name === res.current ? `${name} ← 当前` : name, name));
    sel.appendChild(new Option('自定义手输…', CUSTOM_MODEL));
    sel.value = res.models.includes(res.current) ? res.current : CUSTOM_MODEL;
    status.textContent = res.error ? `列表获取失败（仍可手输）：${res.error}` : `${res.models.length} 个模型 · 提供商实时列表`;
  } catch (err) {
    sel.appendChild(new Option('自定义手输…', CUSTOM_MODEL));
    sel.value = CUSTOM_MODEL; status.textContent = `列表加载失败（仍可手输）：${err.message}`;
  }
  $('#model-custom').hidden = sel.value !== CUSTOM_MODEL;
}
async function saveModel() {
  const sel = $('#model-select'), status = $('#model-status');
  const name = (sel.value === CUSTOM_MODEL ? $('#model-custom').value : sel.value).trim();
  if (!name) { status.textContent = '模型名不能为空'; return; }
  const btn = $('#model-save');
  btn.disabled = true; status.textContent = `用「${name}」做一次真实冒烟调用…`;
  try {
    await apiPost('/api/settings', { reason_model: name });
    status.textContent = '✓ 已切换并保存 — CLI 与 Web 共用，重启不丢';
    await loadMeta();
    setTimeout(() => { $('#model-picker').hidden = true; status.textContent = ''; }, 2000);
  } catch (err) {
    status.textContent = `✗ 未保存：${err.message}`;
  } finally { btn.disabled = false; }
}
function init() { bindForms(); bindGlobal(); switchTab(tabFromHash(), false); window.addEventListener('hashchange', () => switchTab(tabFromHash(), false)); loadProfiles(); loadMeta(); }
init();
window.__pi = { state, esc, mdToHtml, relTime, stars, fmtClock, safeUrl, detectReviewLang, render: { event: renderEvent, planCard: renderPlanCard, verdicts: renderVerdicts, result: renderResult, report: renderReportArticle, libraryGrid: renderLibraryGrid, shopCard: renderShopCard, searchRow: renderSearchRow, detail: renderDetail, review: renderReviewCard, hours: renderHours, languageLens: renderLanguageLens }, openDetail, closeDetail, switchTab, loadLibrary, loadScoutPast, startJob };
