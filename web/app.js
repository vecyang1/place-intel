/* placeintel web UI: no-build vanilla JS; dynamic text is escaped before render. */
'use strict';
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, (ch) => ESC_MAP[ch]); }
const PI18N = window.PI18N, ui = (zh, en) => PI18N.pick(zh, en);
PI18N.init();
function t(key, params) { return PI18N.t(key, params); }
function initLanguage(config) { const s = PI18N.init(config); state.translationTarget = s.translationTarget; return s; }
function langPayload(kind) { return PI18N.requestPayload(kind); }
function toDate(v) {
  if (v == null || v === '') return null;
  const d = typeof v === 'number' && Number.isFinite(v) ? new Date(v > 1e12 ? v : v * 1000) : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}
function relTime(v) {
  return PI18N.relTime(v, toDate);
}
function fmtClock(v) { return PI18N.fmtClock(v, toDate); }
function stars(rating) { const n = Number(rating); return rating != null && Number.isFinite(n) ? `★ ${n.toFixed(1)}` : '★ —'; }
function fmtInt(n) { return PI18N.fmtInt(n); }
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
const FETCH_TIMEOUT_MS = 120000; // generous: covers slow AI reasoning, still bails on a hung backend
const fetchT = (path, opts = {}) => fetch(path, { ...opts, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) });
async function apiGet(path) {
  const res = await fetchT(path, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status} — GET ${path}`);
  return res.json();
}
async function apiPost(path, body) {
  const res = await fetchT(path, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail || ''; } catch { /* not json */ }
    throw new Error(`HTTP ${res.status} — POST ${path}${detail ? `（${detail}）` : ''}`);
  }
  return res.json();
}
async function apiDelete(path) { const res = await fetchT(path, { method: 'DELETE', headers: { Accept: 'application/json' } }); if (!res.ok) throw new Error(`HTTP ${res.status} — DELETE ${path}`); return res.json(); }
const POLL_MS = 2000, MAX_POLL_FAILS = 5;
const txTarget = () => PI18N.translationTarget();
const txLabel = (target) => PI18N.labels[target] || target.toUpperCase();
const txButtonLabel = (target) => `${ui('译文', 'Translate')} ${txLabel(target)}`;
const TAB_NAMES = ['scout', 'shop', 'library', 'ask'];
const tabFromHash = () => (TAB_NAMES.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'scout');
const SEARCH_ROW_CHIP_LIMIT = 8, LIBRARY_PAGE_SIZE = 12, LIBRARY_FILTERS = '#library-sort,#library-category,#library-freshness,#library-risk,#library-language,#library-cached,#library-report';
const state = { tab: 'scout', profiles: [], places: [], libraryLoaded: false, libraryLimit: LIBRARY_PAGE_SIZE, libraryCompare: [], compareDetails: {}, compareLoading: false, jobs: { scout: null, shop: null }, detail: null, dossierJob: null, detailReturnFocus: null, photoReturnFocus: null, photoGallery: [], photoIndex: 0, photoZoom: 1, photoPreloads: [], meta: null, config: null, translationTarget: txTarget(), reportOriginals: {}, searches: [], commandMode: 'scout', commandManual: false }; // meta={version, reason/translate/embed}
function loadingHtml(msg) { return `<p class="loading">${esc(msg)} <span class="dots">●●●</span></p>`; }
function errorHtml(msg) { return `<div class="error-box"><span class="error-label">出错 error</span>${esc(msg)}</div>`; }
function emptyHtml(msg, gotoTab, gotoLabel) { const btn = gotoTab ? `<button type="button" class="btn-ghost" data-goto="${esc(gotoTab)}">${esc(gotoLabel || t('goto.scout'))}</button>` : ''; return `<div class="empty">${esc(msg)}${btn}</div>`; }
function commandLabels() { return { scout: t('button.scout'), shop: t('button.shop'), ask: t('button.ask') }; }
function commandGuess(text) { const q = text.trim(); if (!q) return { mode: 'scout', reason: t('reason.empty') }; if (/google\.[^\s]*\/maps|\/maps\/place|maps\.app\.goo\.gl|goo\.gl\/maps/i.test(q)) return { mode: 'shop', reason: t('reason.maps') }; if ((/[?？]/.test(q) || /^(哪|谁|是否|有没有|can|does|do|which|what|where|how)\b/i.test(q)) && state.searches.length) return { mode: 'ask', reason: t('reason.ask') }; if (q.length <= 60 && !/(找|租|学|推荐|附近|哪家|best|find|near|nearby|rental|lesson|lessons|restaurant|coffee|cafe)/i.test(q)) return { mode: 'shop', reason: t('reason.shopname') }; return { mode: 'scout', reason: t('reason.scout') }; }
function setCommandMode(mode, manual = false, reason = '') { const labels = commandLabels(); state.commandMode = labels[mode] ? mode : 'scout'; if (manual) state.commandManual = true; $$('[data-command-mode]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.commandMode === state.commandMode))); const submit = $('#scout-submit'), why = $('#command-reason'); if (submit) submit.textContent = labels[state.commandMode]; if (why) why.textContent = reason || t('reason.selected', { mode: t(`mode.${state.commandMode}`) }); }
function refreshCommandMode() { const q = $('#scout-query')?.value || ''; if (!q.trim()) state.commandManual = false; if (!state.commandManual) { const g = commandGuess(q); setCommandMode(g.mode, false, g.reason); } }
function matchingScout(query, near) { const q = query.trim().toLowerCase(), n = near.trim().toLowerCase(), fresh = Date.now() / 1000 - 14 * 86400; return state.searches.find((s) => String(s.query || '').trim().toLowerCase() === q && (!n || String(s.location || '').trim().toLowerCase() === n) && Number(s.created_at || 0) >= fresh); }
function renderPlanCard(plan) {
  if (!plan) return '';
  const queries = (plan.queries || []).map((q) => `<span class="chip">${esc(q)}</span>`).join('');
  const metaBits = [plan.near ? `near · ${esc(plan.near)}` : '', plan.profile ? `profile · ${esc(plan.profile)}` : '', plan.report_lang ? `lang · ${esc(plan.report_lang)}` : ''].filter(Boolean).join('<span class="sep">/</span>');
  return `<div class="plan-card"><div class="plan-label">${ui('AI 的计划 · the plan', 'The plan')}</div>${plan.reasoning ? `<p class="plan-reasoning">${esc(plan.reasoning)}</p>` : ''}${plan.intent ? `<p class="plan-intent">${ui('意图', 'Intent')} — ${esc(plan.intent)}</p>` : ''}${queries ? `<div class="plan-queries"><span class="plan-q-label">${ui('实际执行的搜索', 'Searches run')}</span>${queries}</div>` : ''}${metaBits ? `<p class="plan-meta">${metaBits}</p>` : ''}</div>`;
}
function renderVerdicts(verdicts) {
  if (!Array.isArray(verdicts) || !verdicts.length) return '';
  const rows = verdicts.map((v) => `<li class="verdict ${v.relevant ? 'is-kept' : 'is-cut'}"><span class="verdict-mark">${v.relevant ? '✓' : '✕'}</span><span class="verdict-name">${esc(v.name)}</span>${v.reason ? `<span class="verdict-reason chip">${esc(v.reason)}</span>` : ''}</li>`).join('');
  return `<ul class="verdicts">${rows}</ul>`;
}
function renderEvent(ev) {
  const meta = PI18N.stageLabel(ev.stage);
  let extra = '';
  if (ev.stage === 'plan' && ev.data) extra = renderPlanCard(ev.data);
  if (ev.stage === 'filter' && ev.data) extra = renderVerdicts(ev.data.verdicts);
  const tone = /重试|retry/i.test(ev.msg || '') ? ' tl-retry' : /缓存|cache/i.test(ev.msg || '') ? ' tl-cache' : '';
  return `<li class="tl-item tl-${esc(ev.stage || 'misc')}${ev.stage === 'done' ? ' tl-done' : ''}${tone}"><span class="tl-dot"></span><div class="tl-content"><div class="tl-meta"><span class="tl-stage">${esc(meta)}</span><time class="tl-time">${esc(fmtClock(ev.t))}</time></div>${ev.msg ? `<p class="tl-msg">${esc(ev.msg)}</p>` : ''}${extra}</div></li>`;
}
function compareTrayHtml() { return `<div id="compare-tray" class="compare-tray" aria-live="polite">${ui('选择 2-5 家加入对比。', 'Select 2-5 shops to compare.')}</div>`; }
function refreshCompareTray(scope) { const btns = $$('[data-compare-place][aria-pressed="true"]', scope), picks = btns.map((b) => ({ place_id: b.dataset.comparePlace, name: b.dataset.placeName, rating: b.dataset.placeRating, review_count: b.dataset.reviewCount, address: b.dataset.placeAddress, cached_reviews: b.dataset.cachedReviews })), tray = $('#compare-tray', scope); if (picks.length >= 2) loadCompareDetails(picks); if (tray) tray.innerHTML = picks.length ? `<span>${ui('对比', 'Compare')} ${picks.length}/5</span>${picks.map((p) => `<span class="chip">${esc(p.name)}</span>`).join('')}${picks.length >= 2 ? renderCompareBoard(picks) : ''}` : ui('选择 2-5 家加入对比。', 'Select 2-5 shops to compare.'); }
function toggleCompare(btn) { const scope = btn.closest('.job-results') || document, on = btn.getAttribute('aria-pressed') !== 'true'; if (on && $$('[data-compare-place][aria-pressed="true"]', scope).length >= 5) return; btn.setAttribute('aria-pressed', String(on)); btn.textContent = on ? ui('已加入', 'Added') : ui('加入对比', 'Compare'); refreshCompareTray(scope); }
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
  if (!result) return emptyHtml(ui('任务完成但没有返回结果。', 'The job finished but returned no results.'));
  const places = result.places || [];
  const reports = result.reports || [];
  const errors = result.errors || [];
  const deepIds = new Set(reports.map((r) => r.place_id));
  const cut = (result.filtered || []).filter((v) => !v.relevant);
  const parts = [];
  parts.push(`<p class="result-summary">${ui('找到', 'Found')} <strong>${places.length}</strong> ${ui('家 · 深挖', 'shops ·')} <strong>${reports.length}</strong> ${ui('份报告', 'reports')}${
    errors.length ? ` · <span class="warn">${errors.length} ${ui('个警告', 'warnings')}</span>` : ''}</p>`);
  if (result.plan) parts.push(renderPlanCard(result.plan));
  if (places.length) {
    parts.push(compareTrayHtml());
    parts.push(`<div class="place-list">${places.map((p) => `<div class="place-pick"><button type="button" class="place-row${deepIds.has(p.place_id) ? ' is-deep' : ''}" data-open-place="${esc(p.place_id)}">
      <span class="place-rating">${esc(stars(p.rating))}</span>
      <span class="place-name">${esc(p.name)}</span>
      <span class="place-count">${fmtInt(p.review_count)} ${ui('评价', 'reviews')}${deepIds.has(p.place_id) ? ` · ${ui('已深挖', 'deep-dived')}` : ''}</span>
      ${p.address ? `<span class="place-addr">${esc(p.address)}</span>` : ''}
    </button><button type="button" class="btn-ghost compare-pick" data-compare-place="${esc(p.place_id)}" data-place-name="${esc(p.name)}" data-place-rating="${esc(p.rating ?? '')}" data-review-count="${esc(p.review_count ?? '')}" data-place-address="${esc(p.address || '')}" data-cached-reviews="${esc(p.cached_reviews ?? '')}" aria-pressed="false">${ui('加入对比', 'Compare')}</button></div>`).join('')}</div>`);
  } else {
    parts.push(emptyHtml(ui('一家都没找到 — 换个说法，或在「在哪里」里写明城市。', 'No shops found — try rephrasing, or name the city in "Where".')));
  }
  if (cut.length) {
    parts.push(`<details class="result-cut"><summary>${ui(`AI 排除了 ${cut.length} 家（为什么）`, `AI excluded ${cut.length} shops (why)`)}</summary>${renderVerdicts(result.filtered)}</details>`);
  }
  parts.push(reports.map(renderReportArticle).join(''));
  if (errors.length) {
    parts.push(`<details class="result-errors" open><summary>${ui('警告', 'Warnings')} ${errors.length}</summary><ul>${
      errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></details>`);
  }
  return parts.join('');
}
function photoSourcesHtml(photos, variant = 'strip', placeId = '') { const limit = variant === 'strip' ? 12 : 1, big = variant === 'card' || variant === 'compare', opensDossier = Boolean(big && placeId), xs = (Array.isArray(photos) ? photos : photos ? [photos] : []).filter((p) => safeUrl(p?.url || p?.thumb_url)).slice(0, limit); if (!xs.length) return variant === 'strip' ? '' : `<div class="photo-strip photo-${esc(variant)}"><span class="source-photo is-empty"><span class="photo-label">${ui('没有来源图片', 'no source photo')}</span></span></div>`; return `<div class="photo-strip photo-${esc(variant)}">${xs.map((p) => { const url = safeUrl(p.url) || safeUrl(p.thumb_url), src = safeUrl(p.thumb_url) || url, label = p.kind === 'review' ? ui('评价图片', 'review photo') : ui('来源图片', 'source photo'), meta = [label, p.source, p.author, p.date].filter(Boolean).join(' · '), imgSrc = big ? hiRes(src, 800) : src, trigger = opensDossier ? `data-open-place="${esc(placeId)}" aria-label="${esc(ui('打开档案', 'Open dossier'))}"` : `data-photo-url="${esc(url)}" data-photo-src="${esc(src)}" data-photo-caption="${esc(meta)}" aria-label="${esc(`${ui('打开', 'Open')} ${meta}`)}"`; return `<button type="button" class="source-photo${opensDossier ? ' opens-dossier' : ''}" ${trigger}><img class="source-photo-img" src="${esc(imgSrc)}" alt="${esc(meta)}" loading="lazy" decoding="async" onerror="this.closest('.source-photo')?.classList.add('is-broken')"><span class="photo-label">${esc(label)}</span></button>`; }).join('')}</div>`; }
function renderShopCard(p, featured) {
  const rep = reportKey(p), picked = state.libraryCompare.includes(p.place_id), latest = p.latest_report_at ? `${ui('最近报告', 'Latest report')} ${relTime(p.latest_report_at)}${rep ? ` · ${rep}` : ''}` : '';
  return `<article class="shop-card${featured ? ' is-featured' : ''}">${photoSourcesHtml(p.thumbnail, 'card', p.place_id)}<div class="shop-card-top"><span class="shop-rating">${esc(stars(p.rating))}</span>${p.activity_risk ? `<span class="badge badge-risk">${esc(p.activity_risk.severity === 'high' ? ui('低活跃风险', 'Low activity') : ui('近期偏静', 'Recently quiet'))}</span>` : ''}${p.report_count ? `<span class="badge">${ui('报告', 'Reports')} ×${fmtInt(p.report_count)}</span>` : ''}</div>
    <h3 class="shop-name">${esc(p.name)}</h3>${p.category ? `<p class="shop-cat">${esc(p.category)}</p>` : ''}<p class="shop-stats"><span>${fmtInt(p.review_count)} ${ui('条在列', 'listed')}</span><span>${fmtInt(p.cached_reviews)} ${ui('条已缓存', 'cached')}</span></p>${p.address ? `<p class="shop-addr">${esc(p.address)}</p>` : ''}
    <p class="shop-fresh">${ui('更新于', 'Updated')} ${esc(relTime(p.last_refreshed))}</p>${latest ? `<p class="shop-fresh">${esc(latest)}</p>` : ''}
    <div><button type="button" class="btn-ghost" data-favorite-place="${esc(p.place_id)}" aria-pressed="${p.favorite ? 'true' : 'false'}">${p.favorite ? ui('已收藏', 'Saved') : ui('收藏', 'Save')}</button> <button type="button" class="btn-ghost" data-library-compare="${esc(p.place_id)}" aria-pressed="${picked ? 'true' : 'false'}">${picked ? ui('已对比', 'Comparing') : ui('对比', 'Compare')}</button> <button type="button" class="btn-ghost" data-open-place="${esc(p.place_id)}">${ui('打开档案', 'Open dossier')}</button></div></article>`;
}
function placeScore(p) { const age = Math.max(0, Date.now() / 1000 - (p.last_refreshed || 0)); return (p.report_count || 0) * 650 + (p.cached_reviews || 0) * 2 + (p.review_count || 0) * 0.02 + (Number(p.rating) || 0) * 25 + Math.max(0, 80 - age / 3600) - (p.activity_risk ? 80 : 0); }
const filterVal = (id) => $(`#${id}`)?.value || '', reportKey = (p) => String(p.latest_report_profile || p.report_profile || '').trim(), isStale = (p) => Boolean(p.activity_risk) || Date.now() / 1000 - (p.last_refreshed || 0) > 14 * 86400;
function placeLangs(p) { return [p.languages, p.language_cohorts, p.review_languages, p.language_mix].flatMap((v) => Array.isArray(v) ? v : v ? [v] : []).map((x) => String((typeof x === 'object' ? x.lang || x.code || x.language || x.locale : x) || 'other').toLowerCase().slice(0, 2)).map((v) => ['zh', 'en', 'vi', 'ko'].includes(v) ? v : 'other'); }
function setSelectOptions(id, items, label) { const el = $(`#${id}`); if (!el) return; const old = el.value, names = { 'with-report': t('filter.report.with'), 'no-report': t('filter.report.no') }, vals = [...new Set(items.filter(Boolean).map(String).sort())]; el.innerHTML = `<option value="">${esc(label)}</option>${vals.map((v) => `<option value="${esc(v)}">${esc(names[v] || v)}</option>`).join('')}`; el.value = vals.includes(old) ? old : ''; }
function syncLibraryControls() { setSelectOptions('library-category', state.places.map((p) => p.category), t('filter.category.all')); setSelectOptions('library-report', ['with-report', 'no-report'].concat(state.places.map(reportKey)), t('filter.report.all')); }
function libraryMatches() { const q = ($('#library-search')?.value || '').trim().toLowerCase(), sort = filterVal('library-sort') || 'smart', cat = filterVal('library-category'), fresh = filterVal('library-freshness'), risk = filterVal('library-risk'), lang = filterVal('library-language'), cached = Number(filterVal('library-cached') || 0), rep = filterVal('library-report'); return state.places.filter((p) => (!q || [p.name, p.category, p.address, reportKey(p)].join(' ').toLowerCase().includes(q)) && (!cat || p.category === cat) && (!fresh || (fresh === 'stale' ? isStale(p) : !isStale(p))) && (!risk || (risk === 'risk' ? p.activity_risk : !p.activity_risk)) && (!lang || placeLangs(p).includes(lang)) && (!cached || (p.cached_reviews || 0) >= cached) && (!rep || (rep === 'with-report' ? (p.report_count || 0) > 0 : rep === 'no-report' ? !(p.report_count || 0) : reportKey(p) === rep))).sort((a, b) => sort === 'fresh' ? (b.last_refreshed || 0) - (a.last_refreshed || 0) : sort === 'cached' ? (b.cached_reviews || 0) - (a.cached_reviews || 0) : sort === 'rating' ? (Number(b.rating) || 0) - (Number(a.rating) || 0) : placeScore(b) - placeScore(a)); }
function renderLibraryGrid(places) { return (places || []).map((p) => renderShopCard(p, false)).join(''); }
function compareLangs(reviews) { const groups = languageGroups(reviews || []).slice(0, 3); return groups.length ? groups.map((g) => `${esc(langMeta(g.code)[0])} ${g.count}`).join(' · ') : 'unknown'; }
function compareThemes(reviews) { const m = new Map(); (reviews || []).filter((r) => { const n = Number(r.rating); return Number.isFinite(n) && n > 0 && n <= 3; }).forEach((r) => reviewThemes(reviewBody(r)).forEach((t) => m.set(t[2], (m.get(t[2]) || 0) + 1))); const xs = Array.from(m.entries()).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k]) => k); return xs.length ? xs.join(' · ') : 'unknown'; }
function compareCardHtml(p) { const d = state.compareDetails[p.place_id] || {}, place = d.place || p, reviews = d.reviews || [], rep = d.report || null, j = repJson(rep), risk = place.activity_risk || p.activity_risk, facts = [place.category, place.address, place.phone].filter(Boolean).join(' · ') || ui('未知', 'unknown'), cached = p.cached_reviews ?? reviews.length, advice = (j.walk_in_brief || []).slice(0, 2), pic = place.thumbnail || p.thumbnail || (d.photos || [])[0]; return `<article class="shop-card compare-place-card">${photoSourcesHtml(pic, 'compare', p.place_id)}<div class="shop-card-top"><span class="shop-rating">${esc(stars(place.rating || p.rating))}</span>${risk ? `<span class="badge badge-risk">${esc(risk.label || ui('风险', 'risk'))}</span>` : `<span class="badge">${ui('缓存', 'cache')}</span>`}</div><h3 class="shop-name">${esc(place.name || p.name)}</h3><p class="shop-cat">${fmtInt(place.review_count ?? p.review_count)} ${ui('条在列', 'listed')} · ${fmtInt(cached)} ${ui('条已缓存', 'cached')}</p><dl class="facts"><div class="fact"><dt class="compare-label" style="position:sticky;top:0;background:var(--paper);z-index:1">${ui('事实', 'Facts')}</dt><dd>${esc(facts)}</dd></div><div class="fact"><dt class="compare-label" style="position:sticky;top:0;background:var(--paper);z-index:1">${ui('新鲜度', 'Fresh')}</dt><dd>${esc(`${ui('抓取', 'scrape')} ${relTime(place.last_refreshed || p.last_refreshed)} · ${ui('报告', 'report')} ${rep?.created_at ? relTime(rep.created_at) : relTime(p.latest_report_at)} · ${rep?.profile || reportKey(p) || ui('无报告', 'no report')}`)}</dd></div><div class="fact"><dt class="compare-label" style="position:sticky;top:0;background:var(--paper);z-index:1">${ui('结论', 'Verdict')}</dt><dd>${esc(j.verdict || ui('未知', 'unknown'))}</dd></div><div class="fact"><dt class="compare-label" style="position:sticky;top:0;background:var(--paper);z-index:1">${ui('风险', 'Risk')}</dt><dd>${esc(risk ? `${risk.label || ''} ${risk.reason || ''}`.trim() : ui('未标记', 'none flagged'))}</dd></div><div class="fact"><dt class="compare-label" style="position:sticky;top:0;background:var(--paper);z-index:1">${ui('语言', 'Language')}</dt><dd>${compareLangs(reviews)}</dd></div><div class="fact"><dt class="compare-label" style="position:sticky;top:0;background:var(--paper);z-index:1">${ui('证据', 'Evidence')}</dt><dd>${esc(compareThemes(reviews))}</dd></div><div class="fact"><dt class="compare-label" style="position:sticky;top:0;background:var(--paper);z-index:1">${ui('进店前', 'Walk-in')}</dt><dd>${advice.length ? `<ol>${advice.map((x) => `<li>${esc(x)}</li>`).join('')}</ol>` : ui('未知', 'unknown')}</dd></div></dl><button type="button" class="btn-ghost" data-open-place="${esc(p.place_id)}">${ui('打开档案', 'Open dossier')}</button></article>`; }
function renderCompareBoard(picks) { return picks.length >= 2 ? `<section class="compare-board detail-section" style="width:100%" aria-label="${ui('对比板', 'Compare Board')}"><p class="detail-kicker">${ui('对比板', 'Compare Board')}</p><div class="shop-grid">${picks.map(compareCardHtml).join('')}</div></section>` : `<div class="empty small">${ui('再选一家即可打开对比板。', 'Pick one more shop to open Compare Board.')}</div>`; }
async function loadCompareDetails(picks) { const ids = picks.map((p) => p.place_id).filter((id) => !state.compareDetails[id]); if (!ids.length || state.compareLoading) return; state.compareLoading = true; try { const rows = await Promise.all(ids.map((id) => apiGet(`/api/places/${encodeURIComponent(id)}`).catch((err) => ({ place: { place_id: id, name: id }, reviews: [], report: null, error: err.message })))); rows.forEach((row, i) => { state.compareDetails[ids[i]] = row; }); } finally { state.compareLoading = false; renderLibraryCompare(); $$('.job-results').forEach(refreshCompareTray); } }
function renderLibraryCompare() { const box = $('#library-compare'); if (!box) return; const picks = state.libraryCompare.map((id) => state.places.find((p) => p.place_id === id)).filter(Boolean); if (picks.length >= 2) loadCompareDetails(picks); box.innerHTML = picks.length ? `<div class="compare-tray"><span>Compare ${picks.length}/5</span>${picks.map((p) => `<button type="button" class="chip chip-link" data-open-place="${esc(p.place_id)}">${esc(p.name)} · ${esc(stars(p.rating))} · ${fmtInt(p.cached_reviews)} ${ui('缓存', 'cached')}</button>`).join('')}<button type="button" class="btn-ghost" data-library-compare-clear>${ui('清空', 'Clear')}</button></div>${renderCompareBoard(picks)}` : `<div class="compare-tray">${ui('选择 2-5 家加入 Compare。', 'Select 2-5 shops to add to Compare.')}</div>`; }
function toggleLibraryCompare(btn) { const id = btn.dataset.libraryCompare; let xs = state.libraryCompare.filter((x) => x !== id); if (xs.length === state.libraryCompare.length) { if (xs.length >= 5) return; xs.push(id); } state.libraryCompare = xs; renderLibrary(); }
function renderLibrary() {
  const grid = $('#library-grid'), status = $('#library-status'); if (!grid || !status) return;
  if (!state.places.length) { state.libraryCompare = []; grid.innerHTML = ''; status.innerHTML = emptyHtml(t('empty.library'), 'scout'); renderLibraryCompare(); return; }
  const xs = libraryMatches(), limit = state.libraryLimit || LIBRARY_PAGE_SIZE, shown = xs.slice(0, limit), q = ($('#library-search')?.value || '').trim();
  grid.innerHTML = renderLibraryGrid(shown) + (xs.length > limit ? `<button type="button" class="btn-ghost library-more" data-library-more="1">${ui(`显示更多 ${xs.length - limit} 家`, `Show ${xs.length - limit} more`)}</button>` : '');
  status.innerHTML = xs.length ? `<p class="library-count">${ui('显示', 'Showing')} ${shown.length} / ${state.places.length}${q ? ` · ${ui('搜索', 'Search')} ${esc(q)}` : ''}</p>` : emptyHtml(t('empty.library.nomatch'));
  renderLibraryCompare();
}
function renderSearchRow(s) {
  const places = s.places || [];
  const cutCount = places.filter((p) => p.relevant === false).length;
  const kept = places.filter((p) => p.relevant !== false);
  const more = kept.length > SEARCH_ROW_CHIP_LIMIT ? `<span class="chip chip-more">+${kept.length - SEARCH_ROW_CHIP_LIMIT} ${ui('家', 'more')}</span>` : '';
  const chips = kept.slice(0, SEARCH_ROW_CHIP_LIMIT)
    .map((p) => `<button type="button" class="chip chip-link${p.report_count ? ' has-report' : ''}" data-open-place="${esc(p.place_id)}"${p.report_count ? ` title="${esc(`${ui('报告', 'report')} ×${fmtInt(p.report_count)}`)}"` : ''}>${esc(p.name)}</button>`)
    .join('') + more;
  return `<li class="search-row">
    <div class="search-main">
      <span class="search-query">${esc(s.query)}</span>
      ${s.location ? `<span class="search-loc">@ ${esc(s.location)}</span>` : ''}
      <span class="search-meta">${esc([s.source, cutCount ? ui(`AI 排除 ${cutCount} 家`, `AI cut ${cutCount}`) : '', relTime(s.created_at)].filter(Boolean).join(' · '))}</span>
    </div>
    ${chips ? `<div class="search-places">${chips}</div>` : ''}
  </li>`;
}
function renderHours(hoursJson) {
  if (!hoursJson) return ''; let h = hoursJson;
  if (typeof h === 'string') { try { h = JSON.parse(h); } catch { return esc(hoursJson); } }
  if (Array.isArray(h)) return h.map((x) => esc(String(x))).join('<br>');
  if (h && typeof h === 'object') return Object.entries(h).map(([k, v]) => `${esc(k)} — ${esc(String(v))}`).join('<br>');
  return esc(String(hoursJson));
}
const RATING_FILTERS = PI18N.ratingFilters;
const langMeta = PI18N.langMeta, reviewBody = PI18N.reviewBody, detectReviewLang = PI18N.detectReviewLang, reviewThemes = PI18N.reviewThemes, reviewRatingBand = PI18N.reviewRatingBand, languageGroups = PI18N.languageGroups;
function renderLanguageLens(reviews) {
  if (!reviews.length) return '';
  const groups = languageGroups(reviews);
  const filters = ['all', ...groups.map((g) => g.code)].map((code) => { const m = code === 'all' ? [ui('全部', 'All'), ''] : langMeta(code); return `<button type="button" class="lang-filter${code === 'all' ? ' is-active' : ''}" data-review-lang-filter="${esc(code)}" aria-pressed="${code === 'all'}">${esc(m[0])}${m[1] ? `<span>${esc(m[1])}</span>` : ''}</button>`; }).join('');
  const ratingCounts = reviews.reduce((m, r) => { const k = reviewRatingBand(r.rating); m[k] = (m[k] || 0) + 1; return m; }, { all: reviews.length });
  const ratingFilters = RATING_FILTERS.map(([code, zh, en]) => `<button type="button" class="rating-filter${code === 'all' ? ' is-active' : ''}" data-review-rating-filter="${esc(code)}" aria-pressed="${code === 'all'}">${esc(ui(zh, en))}<span>${ratingCounts[code] || 0}</span></button>`).join('');
  const cards = groups.slice(0, 6).map((g) => {
    const m = langMeta(g.code), avg = g.count ? (g.sum / g.count).toFixed(1) : '—';
    const themes = Array.from(g.themes.values()).sort((a, b) => b.count - a.count).slice(0, 4).map((x) => `<span>${esc(ui(x.row[1], x.row[2]))}<small>${x.count}</small></span>`).join('');
    return `<article class="language-card" data-review-lang-card="${esc(g.code)}"><h4>${esc(m[0])}</h4><p>${g.count} ${ui('条', 'reviews')} · ★ ${avg} · ${esc(m[2])}</p><div class="language-themes">${themes}</div>${g.sample ? `<blockquote>${esc(g.sample)}</blockquote>` : ''}</article>`;
  }).join('');
  const target = `<label class="translation-target-wrap">${ui('译为', 'Translate to')} <select class="translation-target" aria-label="${ui('翻译目标语言', 'translation target language')}">${PI18N.languageOptionsHtml(state.translationTarget)}</select></label>`;
  return `<section class="language-lens" aria-label="${ui('评价语言视角', 'review language lens')}"><div class="language-lens-head"><div><h3>${ui('语言视角', 'Language lens')}</h3><p>${ui('语言页签保留给读原文；细分洞察可展开。', 'Language tabs keep originals readable; expand for grouped insights.')}</p></div><div class="language-actions">${target}<p class="review-filter-count" aria-live="polite">${ui('显示全部', 'Showing all')} ${reviews.length}</p></div></div><div class="language-filters">${filters}</div><div class="rating-filters">${ratingFilters}</div><details class="language-insights"><summary>${ui('展开语言洞察', 'Show language insights')} <span>${groups.length}</span></summary><div class="language-grid">${cards}</div></details></section>`;
}
function renderReviewCard(r) {
  const lang = detectReviewLang(reviewBody(r));
  const dateStr = typeof r.review_date === 'number' ? relTime(r.review_date) : (r.review_date || '');
  const m = langMeta(lang);
  const target = state.translationTarget;
  const tx = r.review_id && r.text ? `<button type="button" class="review-translate" data-review-translate="${esc(r.review_id)}" data-review-translate-target="${target}">${esc(txButtonLabel(target))}</button>` : '';
  return `<article class="review" data-review-lang="${esc(lang)}" data-review-rating="${esc(reviewRatingBand(r.rating))}"><header class="review-meta">
      <span class="review-stars">${esc(stars(r.rating))}</span><span class="review-author">${esc(r.author || ui('匿名', 'Anonymous'))}</span><span class="review-lang">${esc(m[0])}</span>${dateStr ? `<span class="review-date">${esc(dateStr)}</span>` : ''}${tx}</header>
    ${r.text ? `<p class="review-text">${esc(r.text)}</p>` : ''}
    ${r.owner_response ? `<div class="owner-reply"><span class="owner-label">${ui('店家回复', 'Owner reply')}</span><p>${esc(r.owner_response)}</p></div>` : ''}
  </article>`;
}
function repJson(rep) { try { return typeof rep?.json === 'string' ? JSON.parse(rep.json) : (rep?.json || {}); } catch { return {}; } }
function renderDossierBrief(p, reviews, rep) {
  const j = repJson(rep), hard = (((j.dimensions || {}).hard_facts || {}).findings || []).map((f) => f.finding), facts = hard.concat([p.address && `${ui('地址', 'Address')} ${p.address}`, p.phone && `${ui('电话', 'Phone')} ${p.phone}`, p.website && `${ui('网站', 'Website')} ${p.website}`]).filter(Boolean).slice(0, 3), bullets = (j.walk_in_brief || []).slice(0, 3);
  const risk = p.activity_risk ? `${p.activity_risk.label || ui('需核实', 'verify')} · ${p.activity_risk.reason || ''}` : ui('未发现低活跃风险', 'No low-activity risk flagged');
  return `<section class="detail-section dossier-brief" aria-label="${ui('决策简报', 'decision brief')}"><p class="detail-kicker">${ui('决策简报', 'Decision brief')}</p><p><strong>${esc(j.verdict || ui('先看事实，再决定是否进店。', 'Check the facts before deciding whether to walk in.'))}</strong></p><p class="activity-risk${p.activity_risk ? '' : ' is-clear'}">${esc(risk)}</p><p class="report-meta-line">${ui('更新于', 'Updated')} ${esc(relTime(p.last_refreshed))}${rep?.created_at ? ` · ${ui('报告', 'report')} ${esc(relTime(rep.created_at))}` : ''} · ${ui('已缓存', 'cached')} ${reviews.length} ${ui('条', 'reviews')}</p>${facts.length ? `<dl class="facts">${facts.map((f) => `<div class="fact"><dt>${ui('事实', 'Fact')}</dt><dd>${esc(f)}</dd></div>`).join('')}</dl>` : ''}${bullets.length ? `<ol>${bullets.map((b) => `<li>${esc(b)}</li>`).join('')}</ol>` : `<div class="empty small">${ui('还没有报告建议，可先看事实和原文评价。', 'No report advice yet. Check facts and original reviews first.')}</div>`}</section>`;
}
function renderDetail(data) {
  const p = (data && data.place) || {};
  const reviews = (data && data.reviews) || [];
  const rep = (data && data.report) || null;
  const facts = [], listedReviews = Number(p.review_count) || 0, cacheGap = listedReviews > reviews.length, cacheLabel = cacheGap ? `${reviews.length} / ${fmtInt(listedReviews)}` : `${reviews.length}`;
  const addFact = (label, html) => { if (html) facts.push(`<div class="fact"><dt>${label}</dt><dd>${html}</dd></div>`); };
  addFact(ui('地址', 'Address'), p.address && esc(p.address));
  addFact(ui('电话', 'Phone'), p.phone && esc(p.phone));
  const site = safeUrl(p.website);
  addFact(ui('网站', 'Website'), site && `<a href="${esc(site)}" target="_blank" rel="noopener noreferrer">${esc(site)}</a>`);
  addFact(ui('营业时间', 'Hours'), renderHours(p.hours_json));
  const maps = safeUrl(p.maps_url) || (p.name ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([p.name, p.address].filter(Boolean).join(' '))}` : null);
  return `<header class="detail-shop">
    <p class="detail-kicker">${esc(p.category || ui('店铺', 'Shop'))} · ${esc(stars(p.rating))} · ${fmtInt(p.review_count)} ${ui('条在列', 'listed')}</p>
    <h2 class="detail-name">${esc(p.name || ui('未命名', 'Unnamed'))}</h2>
    ${p.activity_risk ? `<p class="activity-risk">${esc(p.activity_risk.label)} · ${esc(p.activity_risk.reason)}</p>` : ''}
    <p class="detail-fresh">${ui('已缓存', 'Cached')} ${cacheLabel} ${ui('条评价', 'reviews')} · ${ui('更新于', 'Updated')} ${esc(relTime(p.last_refreshed))}
      ${maps ? `<a class="detail-map-link" href="${esc(maps)}" target="_blank" rel="noopener noreferrer">📍 ${ui('在 Google 地图打开', 'Open in Google Maps')} ↗</a>` : ''}
      ${cacheGap ? `<button type="button" class="btn-ghost" data-generate-report="${esc(p.place_id)}" data-report-action="refresh-reviews" data-report-refresh="reviews" data-place-name="${esc(p.name || '')}" data-place-address="${esc(p.address || '')}">${ui('补抓评价', 'Fetch more reviews')} ↻</button>` : ''}
      <button type="button" class="btn-ghost btn-danger" data-delete-place="${esc(p.place_id)}" data-place-name="${esc(p.name || '')}">${ui('从缓存移除', 'Remove from cache')} ✕</button>
    </p>
  </header>
  ${photoSourcesHtml(data.photos, 'strip')}
  ${renderDossierBrief(p, reviews, rep)}
  <section class="detail-section">
    <form class="ask-shop-form" data-place-id="${esc(p.place_id)}">
      <label>${ui('只问这家店', 'Ask this shop')}</label>
      <div class="ask-inline">
        <input type="text" class="ask-shop-input" autocomplete="off" placeholder="例：他们家能修琴吗？老板态度怎么样？…">
        <button type="submit" class="btn-small">${ui('问', 'Ask')} →</button>
      </div>
    </form>
    <div class="qa-history" data-qa-scope="${esc(p.place_id)}"></div>
    <div class="ask-shop-answer"></div>
  </section>
  ${facts.length ? `<section class="detail-section"><dl class="facts detail-facts">${facts.join('')}</dl></section>` : ''}
  <section class="detail-section"><div data-report-slot>
    ${rep
    ? `<div class="report-meta-line">${ui('最新报告', 'Latest report')}${rep.profile ? ` · ${esc(rep.profile)}` : ''}${rep.model ? ` · <span class="model-tag">${esc(rep.model)}</span>` : ''} · ${esc(relTime(rep.created_at))}</div>
       ${renderReportTranslateControls(rep)}<article class="report"><div class="report-body">${mdToHtml(rep.md)}</div></article>`
    : `<div class="empty small">${ui('这家店还没有报告。', 'This place has no report yet.')} <button type="button" class="btn-ghost" data-generate-report="${esc(p.place_id)}" data-report-action="generate" data-place-name="${esc(p.name || '')}" data-place-address="${esc(p.address || '')}">${ui('生成报告', 'Generate report')} →</button></div>`}
    </div>
  </section>
  <details class="detail-reviews">
    <summary>${ui(`评价原文 reviews · ${reviews.length} 条`, `Reviews · ${reviews.length}`)}</summary>
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
  const job = state.jobs[kind]; if (job) { job.active = false; if (job.es) job.es.close(); }
  const els = jobEls(kind); els.submit.disabled = false; removeLive(kind);
  els.results.innerHTML = errorHtml(msg);
}
function pauseJobStream(kind) { const job = state.jobs[kind]; if (!job || !job.active) return; job.paused = true; if (job.es) { job.es.close(); job.es = null; } if (job.timer) { clearTimeout(job.timer); job.timer = null; } } // pause releases SSE/poll on hidden tab
function resumeJobStream(kind) { const job = state.jobs[kind]; if (!job || !job.active || job.es || job.timer) return; job.paused = false; if (job.id) streamJob(kind); } // clear pause even mid-POST (id still null) so the pending startJob→streamJob attaches
async function startJob(kind, path, body) {
  const prev = state.jobs[kind];
  if (prev && prev.timer) clearTimeout(prev.timer);
  if (prev && prev.es) prev.es.close();
  if (prev) prev.active = false;
  const job = { id: null, path, body, rendered: 0, lastEventId: 0, fails: 0, timer: null, es: null, active: true, paused: false };
  state.jobs[kind] = job;
  const els = jobEls(kind);
  els.submit.disabled = true;
  els.wrap.hidden = false;
  els.results.innerHTML = '';
  els.jobid.textContent = '';
  els.timeline.innerHTML = `<li class="tl-item tl-live" id="${kind}-live" aria-live="polite">
    <span class="tl-dot dot-live"></span>
    <div class="tl-content"><p class="tl-msg muted">${ui('已提交，等待后端响应…', 'Submitted, waiting for the backend…')}</p></div>
  </li>`;
  try {
    const { job_id } = await apiPost(path, body);
    if (state.jobs[kind] !== job || !job.active) return;
    job.id = job_id;
    els.jobid.textContent = `job ${job_id}`;
    streamJob(kind);
  } catch (err) {
    failJob(kind, ui(`提交失败：${err.message} — 确认后端在运行后重试。`, `Submit failed: ${err.message} — make sure the backend is running, then retry.`));
  }
}
function streamJob(kind) {
  const job = state.jobs[kind]; if (!job || job.paused) return; if (!window.EventSource || !job.id) return pollJob(kind); // paused → resumeJobStream re-opens when the tab is shown
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
      failJob(kind, ui(`轮询失败：${err.message} — 后端可能掉线了。修好后重新提交即可，已完成的步骤有缓存，几乎不花时间。`, `Polling failed: ${err.message} — the backend may be offline. Fix it and resubmit; completed steps are cached and cost almost nothing.`));
      return;
    }
    setLiveMsg(kind, ui(`轮询失败，重试中（${job.fails}/${MAX_POLL_FAILS}）…`, `Polling failed, retrying (${job.fails}/${MAX_POLL_FAILS})…`));
    if (!job.paused) job.timer = setTimeout(() => pollJob(kind), POLL_MS);
    return;
  }
  appendEvents(kind, data.events || []);
  if (data.status === 'running') {
    setLiveMsg(kind, ui('运行中…', 'Running…'));
    if (!job.paused) job.timer = setTimeout(() => pollJob(kind), POLL_MS);
    return;
  }
  job.active = false;
  const els = jobEls(kind);
  els.submit.disabled = false;
  if (job.es) job.es.close();
  removeLive(kind);
  if (data.status === 'error') {
    els.results.innerHTML = errorHtml(ui(`任务失败：${data.error || '未知错误'} — 可直接重新提交，已完成的步骤会命中缓存。`, `Job failed: ${data.error || 'unknown error'} — just resubmit; completed steps hit the cache.`));
    return;
  }
  if (data.status === 'interrupted') { els.results.innerHTML = `<div class="error-box"><span class="error-label">中断 interrupted</span>${esc(`${ui('任务中断', 'Interrupted')}：${data.retry_hint || data.error || ui('后端重启，中止了这个任务。', 'The backend restarted and aborted this job.')}`)}<button type="button" class="btn-ghost" data-retry-job="${esc(kind)}">${ui('用缓存重试 →', 'Retry with cache →')}</button></div>`; return; }
  els.results.innerHTML = renderResult(data.result);
  if (kind === 'scout') loadScoutPast();
  if (state.libraryLoaded) loadLibrary(); // keep library tab fresh in background
}
async function loadScoutPast() {
  const list = $('#scout-past-list'), status = $('#scout-past-status'); if (!list || !status) return;
  if (!list.innerHTML) status.innerHTML = loadingHtml(ui('读取过去侦察', 'Reading past scouts'));
  try { state.searches = await apiGet('/api/searches') || []; list.innerHTML = state.searches.slice(0, 8).map(renderSearchRow).join(''); status.innerHTML = state.searches.length ? '' : emptyHtml(ui('还没有过去侦察。', 'No past scouts yet.')); refreshCommandMode(); }
  catch (err) { list.innerHTML = ''; status.innerHTML = errorHtml(ui(`读取过去侦察失败：${err.message}`, `Failed to read past scouts: ${err.message}`)); }
}
async function loadLibrary() {
  const grid = $('#library-grid'), status = $('#library-status'), hList = $('#history-list'), hStatus = $('#history-status');
  if (!grid.innerHTML) status.innerHTML = loadingHtml(t('loading.library'));
  const [placesR, searchesR] = await Promise.allSettled([apiGet('/api/places'), apiGet('/api/searches')]);
  if (placesR.status === 'fulfilled') {
    state.places = placesR.value || [];
    syncLibraryControls();
    renderLibrary();
  } else {
    grid.innerHTML = '';
    status.innerHTML = errorHtml(ui(`读取资料库失败：${placesR.reason.message}`, `Failed to read Library: ${placesR.reason.message}`));
  }
  if (searchesR.status === 'fulfilled') {
    state.searches = searchesR.value || [];
    hList.innerHTML = state.searches.map(renderSearchRow).join('');
    hStatus.innerHTML = state.searches.length ? '' : emptyHtml(t('empty.history'));
  } else {
    hList.innerHTML = '';
    hStatus.innerHTML = errorHtml(ui(`读取历史失败：${searchesR.reason.message}`, `Failed to read history: ${searchesR.reason.message}`));
  }
}
async function toggleFavorite(btn) { const id = btn.dataset.favoritePlace, next = btn.getAttribute('aria-pressed') !== 'true'; btn.disabled = true; try { await apiPost(`/api/places/${encodeURIComponent(id)}/favorite`, { favorite: next }); await loadLibrary(); } catch (err) { window.alert(ui(`收藏失败：${err.message}`, `Save failed: ${err.message}`)); } finally { btn.disabled = false; } }
async function openDetail(placeId) {
  const overlay = $('#detail-overlay');
  const body = $('#detail-body');
  const close = $('#detail-close');
  if (overlay.hidden) state.detailReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  overlay.hidden = false;
  $('.shell').inert = true; // background app non-interactive + hidden from assistive tech while the dossier is modal
  document.body.classList.add('no-scroll');
  body.innerHTML = loadingHtml(ui('读取店铺档案', 'Reading shop dossier'));
  close.focus({ preventScroll: true });
  try {
    const data = await apiGet(`/api/places/${encodeURIComponent(placeId)}`);
    state.detail = data;
    body.innerHTML = renderDetail(data);
    applyReportTranslationPreference(body);
    body.scrollTop = 0;
    loadQaHistory(placeId); // past Q&A for this shop, re-askable
  } catch (err) {
    body.innerHTML = errorHtml(ui(`读取失败：${err.message}`, `Load failed: ${err.message}`));
  }
}
function closeDetail() {
  $('#detail-overlay').hidden = true;
  $('.shell').inert = false;
  document.body.classList.remove('no-scroll');
  state.detail = null;
  if (state.dossierJob) { try { if (state.dossierJob.es) state.dossierJob.es.close(); } catch (e) { /* already closed */ } clearTimeout(state.dossierJob.timer); state.dossierJob = null; } // stop in-dossier report stream; server job finishes on its own
  const returnFocus = state.detailReturnFocus;
  state.detailReturnFocus = null;
  if (returnFocus && document.contains(returnFocus)) returnFocus.focus({ preventScroll: true });
  else $(`#tab-${state.tab}`)?.focus({ preventScroll: true }); // trigger gone (e.g. deleted card) — keep focus in the document
}
function setPhotoZoom(next) { const z = Math.max(0.5, Math.min(3, Math.round(next * 100) / 100)), stage = $('.photo-lightbox-stage'), canvas = $('.photo-lightbox-canvas'); state.photoZoom = z; if (canvas) { canvas.style.width = `${z * 100}%`; canvas.style.height = `${z * 100}%`; } if (stage) requestAnimationFrame(() => { if (z <= 1) { stage.scrollLeft = 0; stage.scrollTop = 0; } else { stage.scrollLeft = (stage.scrollWidth - stage.clientWidth) / 2; stage.scrollTop = (stage.scrollHeight - stage.clientHeight) / 2; } }); $('#photo-lightbox-zoom-label').textContent = `${Math.round(z * 100)}%`; $('#photo-lightbox-zoom-out').disabled = z <= 0.5; $('#photo-lightbox-zoom-in').disabled = z >= 3; }
function showPhotoAt(index) { const xs = state.photoGallery || []; if (!xs.length) return; const i = (index + xs.length) % xs.length, btn = xs[i], url = safeUrl(btn.dataset.photoUrl), src = safeUrl(btn.dataset.photoSrc) || url; if (!url || !src) return; state.photoIndex = i; $('#photo-lightbox-img').src = hiRes(url, 1600); $('#photo-lightbox-img').alt = btn.querySelector('img')?.alt || 'source photo'; $('#photo-lightbox-caption').textContent = btn.dataset.photoCaption || $('#photo-lightbox-img').alt; $('#photo-lightbox-source').href = url; $('#photo-lightbox-source').textContent = url; $('#photo-lightbox-count').textContent = `${i + 1}/${xs.length}`; $('#photo-lightbox-prev').disabled = xs.length < 2; $('#photo-lightbox-next').disabled = xs.length < 2; setPhotoZoom(1); }
function shiftPhoto(step) { if ((state.photoGallery || []).length < 2) return; showPhotoAt(state.photoIndex + step); }
function preloadPhotoGallery(start = state.photoIndex) { const xs = state.photoGallery || [], seen = new Set(); state.photoPreloads = []; for (let d = 1; d < xs.length; d += 1) [start + d, start - d].forEach((n) => { const u = safeUrl(xs[(n + xs.length) % xs.length]?.dataset.photoUrl); if (!u || seen.has(u)) return; seen.add(u); const img = new Image(); img.decoding = 'async'; img.loading = 'eager'; img.src = hiRes(u, 1600); state.photoPreloads.push(img); }); }
function photoPlaceId(btn) { return btn.closest('[data-photo-place-id]')?.dataset.photoPlaceId || btn.closest('article')?.querySelector('[data-open-place]')?.dataset.openPlace || btn.closest('.place-pick')?.querySelector('[data-open-place]')?.dataset.openPlace || (!$('#detail-overlay')?.hidden && btn.closest('#detail-body') ? state.detail?.place?.place_id : null); }
function photoButtonFromSource(p) { const url = safeUrl(p?.url) || safeUrl(p?.thumb_url), src = safeUrl(p?.thumb_url) || url; if (!url || !src) return null; const label = p.kind === 'review' ? ui('评价图片', 'review photo') : ui('来源图片', 'source photo'), meta = [label, p.source, p.author, p.date].filter(Boolean).join(' · '), btn = document.createElement('button'), img = document.createElement('img'); btn.dataset.photoUrl = url; btn.dataset.photoSrc = src; btn.dataset.photoCaption = meta; img.alt = meta; btn.appendChild(img); return btn; }
async function detailPhotoGallery(btn, fallback) { const placeId = photoPlaceId(btn); if (!placeId || fallback.length > 1) return fallback; try { const cached = state.detail?.place?.place_id === placeId ? state.detail : state.compareDetails[placeId], data = cached || await apiGet(`/api/places/${encodeURIComponent(placeId)}`), xs = (data.photos || []).map(photoButtonFromSource).filter(Boolean); if (!cached) state.compareDetails[placeId] = data; return xs.length > 1 ? xs : fallback; } catch { return fallback; } }
async function openPhotoLightbox(btn) {
  const xs = $$('[data-photo-url]', btn.closest('.photo-strip') || document).filter((x) => safeUrl(x.dataset.photoUrl));
  if (!xs.length) return;
  state.photoReturnFocus = btn; state.photoGallery = xs; $('#photo-lightbox').hidden = false; if (!$('#detail-overlay').hidden) $('#detail-overlay').inert = true; document.body.classList.add('no-scroll'); showPhotoAt(Math.max(0, xs.indexOf(btn))); preloadPhotoGallery(); $('#photo-lightbox-close').focus({ preventScroll: true });
  const richer = await detailPhotoGallery(btn, xs);
  if ($('#photo-lightbox').hidden || state.photoReturnFocus !== btn || richer === xs) return;
  const startUrl = btn.dataset.photoUrl, at = richer.findIndex((x) => x.dataset.photoUrl === startUrl);
  state.photoGallery = richer; showPhotoAt(at >= 0 ? at : 0); preloadPhotoGallery();
}
function closePhotoLightbox() { const box = $('#photo-lightbox'); if (box.hidden) return; box.hidden = true; $('#detail-overlay').inert = false; $('#photo-lightbox-img').removeAttribute('src'); $('#photo-lightbox-source').removeAttribute('href'); $('#photo-lightbox-source').textContent = ''; $('.photo-lightbox-canvas')?.removeAttribute('style'); state.photoGallery = []; state.photoPreloads = []; state.photoIndex = 0; if ($('#detail-overlay').hidden) document.body.classList.remove('no-scroll'); const f = state.photoReturnFocus; state.photoReturnFocus = null; if (f && document.contains(f)) f.focus({ preventScroll: true }); } function changePhotoZoom(btn) { const step = Number(btn.dataset.photoZoom || 0); setPhotoZoom(step ? state.photoZoom + step * 0.25 : 1); } function wheelPhotoZoom(e) { if ($('#photo-lightbox').hidden || !e.deltaY) return; e.preventDefault(); setPhotoZoom(state.photoZoom + (e.deltaY < 0 ? 0.25 : -0.25)); } function trapPhotoFocus(e) { const xs = $$('a[href],button:not([disabled])', $('#photo-lightbox')), first = xs[0], last = xs[xs.length - 1], active = document.activeElement; if (!xs.length) return; if (e.shiftKey && active === first) { e.preventDefault(); return last.focus({ preventScroll: true }); } if (!e.shiftKey && active === last) { e.preventDefault(); return first.focus({ preventScroll: true }); } }
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
  if (!$('#detail-overlay').hidden) closeDetail(); // a dossier drawer shouldn't linger over another tab
  ['scout', 'shop'].forEach((k) => (k === name ? resumeJobStream : pauseJobStream)(k)); // hidden tab's live job releases its stream; visible tab's re-attaches
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
    const body = { query, top: clampInt($('#scout-top').value, 1, 8, 3), max_reviews: clampInt($('#scout-maxr').value, 20, 5000, 300), ...langPayload('report') };
    const near = $('#scout-near').value.trim();
    if (state.commandMode === 'ask') { switchTab('ask'); $('#ask-question').value = query; return runAsk(query, null, $('#ask-answer'), false); }
    if (state.commandMode === 'shop') {
      const shopBody = { target: query, max_reviews: body.max_reviews, ...langPayload('report') };
      if (near) { shopBody.near = near; $('#shop-near').value = near; } if ($('#scout-profile').value) shopBody.profile = $('#scout-profile').value; if ($('#scout-refresh').checked) shopBody.refresh = true;
      $('#shop-target').value = query; switchTab('shop'); return startJob('shop', '/api/shop', shopBody);
    }
    const cached = matchingScout(query, near);
    if (cached && !$('#scout-refresh').checked) { $('#scout-past-status').textContent = ui('命中缓存：下面已有同一侦察；强制刷新才会重新抓取。', 'Cache hit: the same scout is already below; only force-refresh re-fetches.'); return $('#scout-past').scrollIntoView({ block: 'start', behavior: 'smooth' }); }
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
      ...langPayload('report'),
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
function evidenceHtml(items) { const rows = (type) => (items || []).filter((e) => e.type === type), meta = (e) => [e.place_name, e.rating ? `★${e.rating}` : '', e.date || '', e.source_lang ? `${ui('原文', 'source')}:${e.source_lang}` : ''].filter(Boolean).map(esc).join(' · '); const group = (title, type) => rows(type).length ? `<section><h4>${title}</h4>${rows(type).slice(0, 6).map((e) => `<p><span class="model-tag">${meta(e)}</span> ${esc(e.label ? `${e.label}: ${e.value}` : e.text)}</p>`).join('')}</section>` : ''; return rows('listing').length || rows('review').length ? `<div class="answer-evidence">${group(ui('使用的店铺事实', 'Listing facts used'), 'listing')}${group(ui('使用的评价证据', 'Review evidence used'), 'review')}</div>` : ''; }
function renderAnswer(res, q, placeId) {
  const scope = res.cache_scope ? `${res.cache_scope.kind === 'place' ? ui('单店', 'place') : ui('全局', 'global')} ${ui('精确范围', 'exact scope')} · ${res.cache_scope.label || ''}` : ui('精确范围', 'exact scope');
  const fresh = res.evidence_fresh_after ? ` · ${ui('之后没有更新评价', 'no newer reviews since')} ${esc(relTime(res.evidence_fresh_after))}` : '';
  const cachedNote = res.cached ? `<div class="answer-cached">⚡ ${ui('缓存答案', 'Cached answer')} · ${esc(scope)}${fresh} · ${ui('来自', 'from')} ${esc(relTime(res.created_at))}${ui('的相同问题', ' matching question')} <button type="button" class="btn-ghost btn-refresh" data-refresh-q="${esc(q)}" data-refresh-place="${esc(placeId || '')}">${ui('重新推理', 'Re-reason')} ↻</button></div>` : '';
  const modelTag = res.model
    ? `<span class="model-tag">${esc(res.model)}${res.provider ? ` @ ${esc(res.provider)}` : ''}</span>`
    : '';
  return `<div class="answer"><div class="answer-label">${ui('回答', 'Answer')} ${modelTag}</div>${cachedNote}
    <div class="report-body">${mdToHtml(res.answer)}</div>${evidenceHtml(res.evidence)}</div>`;
}
async function runAsk(q, placeId, out, fresh) {
  const submit = $('#ask-submit');
  if (!placeId && submit) submit.disabled = true;
  out.innerHTML = loadingHtml(fresh ? ui('强制重新推理中', 'Force re-reasoning…')
    : placeId ? ui('只检索这家店的评价 + 推理中', 'Searching reviews for this shop + reasoning…') : ui('在整个缓存里检索 + 推理中', 'Searching the whole cache + reasoning…'));
  try {
    const body = { question: q, ...langPayload('answer') };
    if (placeId) body.place_id = placeId;
    if (fresh) body.fresh = true;
    const res = await apiPost('/api/ask', body);
    out.innerHTML = renderAnswer(res, q, placeId);
    loadQaHistory(placeId || null);
  } catch (err) {
    out.innerHTML = errorHtml(`${ui('提问失败', 'Ask failed')}：${err.message}${placeId ? '' : ui('（问缓存只问已有证据；先跑侦察或单店深挖。）', ' (Ask only uses cached evidence. Run Scout or Shop first.)')}`);
  } finally {
    if (!placeId && submit) submit.disabled = false;
  }
}
function renderQaChips(rows) {
  if (!rows || !rows.length) return '';
  const chips = rows.map((r) => {
    const label = r.question.length > 42 ? `${r.question.slice(0, 42)}…` : r.question;
    const place = r.place_id ? (r.place_name || ui('单店', 'this shop')) : '';
    return `<button type="button" class="chip chip-link" data-ask-again="${esc(r.question)}"
      ${place ? `data-ask-place="${esc(r.place_id)}"` : ''}
      title="${esc(place ? `${place} · ` : '')}${esc(relTime(r.created_at))} · ${esc(ui('点击重问（命中缓存则免费秒回）', 'Click to re-ask (cached answers return instantly, free)'))}">${esc(label)}${place ? ` · ${esc(place)}` : ''}</button>`;
  }).join('');
  return `<div class="qa-chips"><span class="qa-chips-label">${ui('问过', 'Asked')}</span>${chips}</div>`;
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
    const photo = e.target.closest('[data-photo-url]'); if (photo) return openPhotoLightbox(photo); const step = e.target.closest('[data-photo-step]'); if (step) return shiftPhoto(Number(step.dataset.photoStep || 0)); const zoom = e.target.closest('[data-photo-zoom]'); if (zoom) return changePhotoZoom(zoom); if (e.target.closest('[data-photo-close]') || e.target.closest('#photo-lightbox-close')) return closePhotoLightbox();
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
    const reportTx = e.target.closest('[data-report-translate]'); if (reportTx) return translateReport(reportTx);
    const reportOriginal = e.target.closest('[data-report-original]'); if (reportOriginal) return restoreReport(reportOriginal);
    const fav = e.target.closest('[data-favorite-place]');
    if (fav) return toggleFavorite(fav);
    const genReport = e.target.closest('[data-generate-report]'); if (genReport) return generateReportInline(genReport);
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
    if (e.target.closest('#system-toggle')) return toggleSystem();
    if (e.target.closest('#language-save')) return saveLanguageSettings();
    if (e.target.closest('#model-switch')) return toggleModelPicker();
    if (e.target.closest('#model-save')) return saveModel();
  });
  document.addEventListener('input', (e) => { if (e.target.closest('#library-search')) { state.libraryLimit = LIBRARY_PAGE_SIZE; renderLibrary(); } }); document.addEventListener('change', (e) => { const sel = e.target.closest('.translation-target'); if (sel) setTranslationTarget(sel); const reportSel = e.target.closest('.report-translation-target'); if (reportSel) setReportTranslationTarget(reportSel); if (e.target.closest(LIBRARY_FILTERS)) { state.libraryLimit = LIBRARY_PAGE_SIZE; renderLibrary(); } }); $('#photo-lightbox').addEventListener('wheel', wheelPhotoZoom, { passive: false });
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
    if (e.key === 'Tab' && !$('#photo-lightbox').hidden) return trapPhotoFocus(e); if (!$('#photo-lightbox').hidden && ['ArrowRight', 'ArrowLeft'].includes(e.key)) { e.preventDefault(); return shiftPhoto(e.key === 'ArrowRight' ? 1 : -1); } if (!$('#photo-lightbox').hidden && ['+', '='].includes(e.key)) { e.preventDefault(); return setPhotoZoom(state.photoZoom + 0.25); } if (!$('#photo-lightbox').hidden && e.key === '-') { e.preventDefault(); return setPhotoZoom(state.photoZoom - 0.25); } if (e.key === 'Tab' && !$('#detail-overlay').hidden) trapDetailFocus(e);
    if (e.key === 'Escape' && !$('#photo-lightbox').hidden) return closePhotoLightbox(); if (e.key === 'Escape' && !$('#detail-overlay').hidden) closeDetail();
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
  if (label) label.textContent = code === 'all' && rating === 'all' ? `${ui('显示全部', 'Showing all')} ${cards.length}` : `${ui('显示', 'Showing')} ${shown} / ${cards.length}`;
}
function setTranslationTarget(sel) {
  const panel = sel.closest('.detail-reviews'), target = PI18N.normalizeTag(sel.value) || 'en';
  if (panel) { panel.dataset.txBatch = String(Number(panel.dataset.txBatch || 0) + 1); delete panel.dataset.txBusy; }
  state.translationTarget = target; PI18N.savePrefs({ translation_target: target });
  $$('.translation-target', panel).forEach((x) => { x.value = target; }); $$('.review-translation', panel).forEach((x) => x.remove());
  $$('[data-review-translate]', panel).forEach((b) => { b.dataset.reviewTranslateTarget = target; b.textContent = txButtonLabel(target); b.disabled = false; });
}
function visibleTranslateButtons(btn) { const panel = btn.closest('.detail-reviews') || document; return $$('[data-review-translate]', panel).filter((b) => !b.closest('.review')?.hidden); }
async function translateOneReview(btn, token) {
  const panel = btn.closest('.detail-reviews');
  if (panel && panel.dataset.txBatch !== token) return;
  const card = btn.closest('.review'), target = btn.dataset.reviewTranslateTarget || state.translationTarget, label = txButtonLabel(target);
  $('.review-translation.is-error', card)?.remove();
  btn.disabled = true; btn.textContent = ui('翻译中…', 'Translating...');
  try {
    const r = await apiPost('/api/reviews/translate', { review_id: btn.dataset.reviewTranslate, target_lang: target });
    if ((panel && panel.dataset.txBatch !== token) || (btn.dataset.reviewTranslateTarget || state.translationTarget) !== target) return;
    card.insertAdjacentHTML('beforeend', `<div class="review-translation"><span>${ui('译文', 'Translation')} ${esc(r.target_lang)}${r.cached ? ` · ${ui('缓存', 'cached')}` : ''}</span><p>${esc(r.text)}</p></div>`);
    btn.textContent = ui('已译', 'Translated');
  } catch (err) {
    if (panel && panel.dataset.txBatch !== token) return;
    card.insertAdjacentHTML('beforeend', `<div class="review-translation is-error">${esc(`${ui('翻译失败', 'Translation failed')}：${err.message}`)}</div>`);
    btn.textContent = label;
  } finally { btn.disabled = false; }
}
async function translateReview(btn) {
  const panel = btn.closest('.detail-reviews'); if (panel?.dataset.txBusy === '1') return;
  const buttons = visibleTranslateButtons(btn), pending = buttons.filter((b) => !$('.review-translation:not(.is-error)', b.closest('.review')));
  if (!pending.length) { buttons.forEach((b) => { const block = $('.review-translation', b.closest('.review')); if (block) { block.hidden = !block.hidden; b.textContent = block.hidden ? txButtonLabel(b.dataset.reviewTranslateTarget || state.translationTarget) : ui('已译', 'Translated'); } }); return; }
  const token = String(Number(panel?.dataset.txBatch || 0) + 1); if (panel) { panel.dataset.txBatch = token; panel.dataset.txBusy = '1'; }
  const controls = panel ? [...buttons, ...$$('.translation-target', panel)] : buttons; controls.forEach((x) => { x.disabled = true; });
  let i = 0; try { await Promise.all(Array.from({ length: Math.min(3, pending.length) }, async () => { while (i < pending.length && (!panel || panel.dataset.txBatch === token)) await translateOneReview(pending[i++], token); })); }
  finally { if (!panel || panel.dataset.txBatch === token) { if (panel) delete panel.dataset.txBusy; controls.forEach((x) => { x.disabled = false; }); } }
}
async function deletePlace(placeId, name) {
  if (!window.confirm(ui(`把「${name || placeId}」连同它缓存的评价、报告、问答一起移除？\n（下次搜到它会重新抓取）`, `Remove "${name || placeId}" along with its cached reviews, reports, and Q&A?\n(It will be re-fetched next time you find it.)`))) return;
  try {
    await apiDelete(`/api/places/${encodeURIComponent(placeId)}`);
    closeDetail();
    loadLibrary();
  } catch (err) {
    window.alert(ui(`删除失败：${err.message}`, `Delete failed: ${err.message}`));
  }
}
async function loadProfiles() { try { const names = await apiGet('/api/profiles'); state.profiles = names; for (const sel of [$('#scout-profile'), $('#shop-profile')]) for (const n of names) sel.appendChild(new Option(n, n)); } catch { /* backend offline — selects keep "auto" only */ } }
function renderLanguageControls(c) { const lang = PI18N.state(), app = c.language?.app_defaults || {}; return `<section class="language-settings"><h4>${ui('语言', 'Language')}</h4><div class="advanced-grid"><label>${ui('界面', 'UI')} <select id="ui-language">${PI18N.languageOptionsHtml(lang.prefs.ui_language || app.ui_language || 'auto', true)}</select></label><label>${ui('回答', 'Ask')} <select id="answer-language">${PI18N.languageOptionsHtml(lang.prefs.answer_language || app.answer_language || 'auto', true)}</select></label><label>${ui('报告', 'Reports')} <select id="report-language">${PI18N.languageOptionsHtml(lang.prefs.report_language || app.report_language || 'auto', true)}</select></label><label>${ui('译文', 'Reviews')} <select id="translation-target-setting">${PI18N.languageOptionsHtml(lang.translationTarget)}</select></label></div><label class="check"><input type="checkbox" id="language-default"> ${ui('设为本应用默认', 'make default for this app')}</label><button type="button" class="btn-model" id="language-save">${ui('保存语言', 'Save language')}</button><span class="model-status" id="language-status" role="status">${ui('当前', 'active')}: ${ui('界面', 'UI')} ${esc(lang.ui)} · ${ui('回答', 'Ask')} ${esc(lang.answer)} · ${ui('报告', 'Reports')} ${esc(lang.report)} · ${ui('译文', 'Reviews')} ${esc(lang.translationTarget)}</span></section>`; }
function renderSystemPanel(c, h) { const s = c.settings || {}, p = c.providers || {}, f = c.feature_status || {}, r = c.runtime?.data_dir || {}, link = c.health || {}; return `<h3>${ui('系统状态', 'System Status')}</h3>${renderLanguageControls(c)}<p>${ui('推理', 'reason')} ${esc(s.reason_model)} · ${ui('译文', 'translation')} ${esc(s.translation_model)} · ${ui('默认回答', 'default answer')} ${esc(s.default_answer_language)} · ${ui('默认报告', 'default report')} ${esc(s.default_report_language || 'auto')} · ${ui('证据', 'evidence')} ${esc(s.evidence_language)} · ${ui('缓存', 'cache')} TTL ${esc(s.cache_ttl_days)} ${ui('天', 'days')}</p><p>${ui('数据目录', 'data dir')} ${r.configured ? ui('已配置', 'configured') : ui('缺失', 'missing')} · ${ui('路径', 'path')} ${r.path_visible ? ui('可见', 'visible') : ui('隐藏', 'hidden')} · ${ui('端口', 'port')} ${esc(c.runtime?.port || '—')} · ${ui('健康', 'health')} ${h?.ok ? 'ok' : ui('需检查', 'check')}</p><p>${ui('提供商状态', 'Provider status')} · ${ui('推理', 'reason')} ${esc(p.reason?.provider || 'unknown')} · ${ui('译文', 'translate')} ${esc(p.translate?.provider || 'unknown')} · ${ui('向量', 'embed')} ${esc(p.embed?.provider || 'unknown')}</p><p>${ui('安装状态', 'Setup state')} · ${ui('推理', 'reasoning')} ${f.reasoning?.available ? 'ok' : ui('需配置', 'setup required')} · ${ui('向量', 'embedding')} ${f.embedding?.available ? 'ok' : ui('需配置', 'setup required')} · ${ui('译文', 'translation')} ${f.translation?.available ? 'ok' : ui('需配置', 'setup required')}</p><p><a href="${esc(link.cheap_url || '/api/health')}">${ui('轻量健康检查', 'cheap health')}</a> · <a href="${esc(link.deep_url || '/api/health/deep')}">${ui('深度健康检查', 'deep health')}</a></p><p id="system-danger"><strong>${ui('危险设置', 'Dangerous settings')}</strong> — ${ui('破坏性缓存/恢复操作只保留在命令行，并且需要确认。', 'destructive cache/restore actions stay in CLI and require confirmation.')}</p>`; }
async function toggleSystem() { const panel = $('#system-panel'); if (!panel) return; if (!panel.hidden) { panel.hidden = true; return; } panel.hidden = false; panel.innerHTML = loadingHtml(ui('读取系统状态', 'Reading system status')); try { const [c, h] = await Promise.all([apiGet('/api/config'), apiGet('/api/health')]); initLanguage(c); panel.innerHTML = renderSystemPanel(c, h); } catch (err) { panel.innerHTML = errorHtml(ui(`系统状态读取失败：${err.message}`, `Failed to read system status: ${err.message}`)); } }
async function saveLanguageSettings() { const prefs = { ui_language: $('#ui-language').value, answer_language: $('#answer-language').value, report_language: $('#report-language').value, translation_target: $('#translation-target-setting').value }; const status = $('#language-status'); PI18N.savePrefs(prefs); state.translationTarget = PI18N.translationTarget(); refreshCommandMode(); if (state.libraryLoaded) { syncLibraryControls(); renderLibrary(); } status.textContent = ui('已存到本浏览器', 'saved in this browser'); if ($('#language-default').checked) { try { await apiPost('/api/settings/language', { ui_language: prefs.ui_language, default_answer_language: prefs.answer_language, default_report_language: prefs.report_language, translation_target: prefs.translation_target, make_default: true }); status.textContent = ui('已存到浏览器和应用默认', 'saved in browser and app defaults'); await loadMeta(); } catch (err) { status.textContent = `${ui('未存为应用默认', 'not saved as app default')}: ${err.message}`; } } }
async function loadMeta() {
  try {
    const c = await apiGet('/api/config');
    state.config = c; initLanguage(c);
    const m = { version: c.version, ...(c.providers || {}) };
    state.meta = m;
    const el = $('#meta-line');
    if (el && m.reason) {
      el.textContent = `${ui('推理', 'Reason')} ${m.reason.model} @ ${m.reason.provider} · ${ui('译文', 'Translate')} ${m.translate?.model || '?'} @ ${m.translate?.provider || '?'} · ${ui('向量', 'Embed')} ${m.embed.model} @ ${m.embed.provider} · v${m.version}`;
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
  status.textContent = ui('实时拉取提供商可用模型…', 'Fetching available models from provider…');
  try {
    const res = await apiGet('/api/models');
    for (const name of res.models) sel.appendChild(new Option(name === res.current ? ui(`${name} ← 当前`, `${name} ← current`) : name, name));
    sel.appendChild(new Option(ui('自定义手输…', 'Custom (type manually)…'), CUSTOM_MODEL));
    sel.value = res.models.includes(res.current) ? res.current : CUSTOM_MODEL;
    status.textContent = res.error ? ui(`列表获取失败（仍可手输）：${res.error}`, `List fetch failed (you can still type manually): ${res.error}`) : ui(`${res.models.length} 个模型 · 提供商实时列表`, `${res.models.length} models · live provider list`);
  } catch (err) {
    sel.appendChild(new Option(ui('自定义手输…', 'Custom (type manually)…'), CUSTOM_MODEL));
    sel.value = CUSTOM_MODEL; status.textContent = ui(`列表加载失败（仍可手输）：${err.message}`, `List load failed (you can still type manually): ${err.message}`);
  }
  $('#model-custom').hidden = sel.value !== CUSTOM_MODEL;
}
async function saveModel() {
  const sel = $('#model-select'), status = $('#model-status');
  const name = (sel.value === CUSTOM_MODEL ? $('#model-custom').value : sel.value).trim();
  if (!name) { status.textContent = ui('模型名不能为空', 'Model name cannot be empty'); return; }
  const btn = $('#model-save');
  btn.disabled = true; status.textContent = ui(`用「${name}」做一次真实冒烟调用…`, `Running a real smoke test with "${name}"…`);
  try {
    await apiPost('/api/settings', { reason_model: name });
    status.textContent = ui('✓ 已切换并保存 — CLI 与 Web 共用，重启不丢', '✓ Switched and saved — shared by CLI and Web, survives restart');
    await loadMeta();
    setTimeout(() => { $('#model-picker').hidden = true; status.textContent = ''; }, 2000);
  } catch (err) {
    status.textContent = ui(`✗ 未保存：${err.message}`, `✗ Not saved: ${err.message}`);
  } finally { btn.disabled = false; }
}
function init() { bindForms(); bindGlobal(); switchTab(tabFromHash(), false); window.addEventListener('hashchange', () => switchTab(tabFromHash(), false)); loadProfiles(); loadMeta(); }
init();
window.__pi = { state, esc, mdToHtml, relTime, stars, fmtClock, safeUrl, detectReviewLang, render: { event: renderEvent, planCard: renderPlanCard, verdicts: renderVerdicts, result: renderResult, report: renderReportArticle, libraryGrid: renderLibraryGrid, shopCard: renderShopCard, searchRow: renderSearchRow, detail: renderDetail, review: renderReviewCard, hours: renderHours, languageLens: renderLanguageLens }, openDetail, closeDetail, switchTab, loadLibrary, loadScoutPast, startJob };
