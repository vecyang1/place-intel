/* placeintel — web UI. Vanilla JS, no frameworks, no build step.
   All state lives in `state`. Render functions are pure (data in → HTML string
   out) and exposed on window.__pi for integration debugging.
   XSS: every piece of dynamic text passes through esc(); markdown is escaped
   FIRST, then transformed. */
'use strict';

/* ============ DOM helpers ============ */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* ============ escaping & formatting (pure) ============ */
const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ESC_MAP[ch]);
}
function toDate(v) {
  if (v == null || v === '') return null;
  if (typeof v === 'number' && Number.isFinite(v)) return new Date(v > 1e12 ? v : v * 1000);
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}
function relTime(v) {
  const d = toDate(v);
  if (!d) return '—';
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 0) return d.toLocaleDateString('zh-CN');
  if (s < 60) return '刚刚';
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)}小时前`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}天前`;
  return d.toLocaleDateString('zh-CN');
}
function fmtClock(v) {
  const d = toDate(v);
  return d ? d.toTimeString().slice(0, 8) : '';
}
function stars(rating) {
  const n = Number(rating);
  return rating != null && Number.isFinite(n) ? `★ ${n.toFixed(1)}` : '★ —';
}
function fmtInt(n) {
  return n == null ? '—' : String(n);
}
function clampInt(v, min, max, dflt) {
  const n = Math.round(Number(v));
  if (!Number.isFinite(n)) return dflt;
  return Math.min(max, Math.max(min, n));
}
function safeUrl(u) {
  return /^https?:\/\//i.test(String(u || '')) ? String(u) : null;
}

/* ============ markdown — escape FIRST, then transform (pure) ============ */
function mdInline(escaped) {
  return escaped
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(（，。、；：—])_([^_\n]+)_/g, '$1<em>$2</em>');
}
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

/* ============ api ============ */
async function apiGet(path) {
  const res = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status} — GET ${path}`);
  return res.json();
}
async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  });
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

/* ============ state ============ */
const POLL_MS = 2000;
const MAX_POLL_FAILS = 5;
const STAGES = {
  plan: { zh: 'AI规划', en: 'plan' },
  search: { zh: '搜索', en: 'search' },
  filter: { zh: 'AI筛选', en: 'filter' },
  reviews: { zh: '抓评价', en: 'reviews' },
  embed: { zh: '向量化', en: 'embed' },
  report: { zh: '推理报告', en: 'report' },
  done: { zh: '完成', en: 'done' },
};
const TAB_NAMES = ['scout', 'shop', 'library', 'ask'];
const tabFromHash = () => (TAB_NAMES.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'scout');
const state = {
  tab: 'scout',
  profiles: [],
  places: [],
  searches: [],
  libraryLoaded: false,
  jobs: { scout: null, shop: null },
  detail: null,
  detailReturnFocus: null,
  meta: null, // {version, reason: {model, provider}, embed: {model, provider}}
};

/* ============ small UI fragments (pure) ============ */
function loadingHtml(msg) {
  return `<p class="loading">${esc(msg)} <span class="dots">●●●</span></p>`;
}
function errorHtml(msg) {
  return `<div class="error-box"><span class="error-label">出错 error</span>${esc(msg)}</div>`;
}
function emptyHtml(msg, gotoTab, gotoLabel) {
  const btn = gotoTab
    ? `<button type="button" class="btn-ghost" data-goto="${esc(gotoTab)}">${esc(gotoLabel || '去侦察 →')}</button>`
    : '';
  return `<div class="empty">${esc(msg)}${btn}</div>`;
}

/* ============ render: timeline (pure) ============ */
function renderPlanCard(plan) {
  if (!plan) return '';
  const queries = (plan.queries || [])
    .map((q) => `<span class="chip">${esc(q)}</span>`).join('');
  const metaBits = [
    plan.near ? `near · ${esc(plan.near)}` : '',
    plan.profile ? `profile · ${esc(plan.profile)}` : '',
    plan.report_lang ? `lang · ${esc(plan.report_lang)}` : '',
  ].filter(Boolean).join('<span class="sep">/</span>');
  return `<div class="plan-card">
    <div class="plan-label">AI 的计划 · the plan</div>
    ${plan.reasoning ? `<p class="plan-reasoning">${esc(plan.reasoning)}</p>` : ''}
    ${plan.intent ? `<p class="plan-intent">意图 — ${esc(plan.intent)}</p>` : ''}
    ${queries ? `<div class="plan-queries"><span class="plan-q-label">实际执行的搜索</span>${queries}</div>` : ''}
    ${metaBits ? `<p class="plan-meta">${metaBits}</p>` : ''}
  </div>`;
}
function renderVerdicts(verdicts) {
  if (!Array.isArray(verdicts) || !verdicts.length) return '';
  const rows = verdicts.map((v) => `<li class="verdict ${v.relevant ? 'is-kept' : 'is-cut'}">
    <span class="verdict-mark">${v.relevant ? '✓' : '✕'}</span>
    <span class="verdict-name">${esc(v.name)}</span>
    ${v.reason ? `<span class="verdict-reason">${esc(v.reason)}</span>` : ''}
  </li>`).join('');
  return `<ul class="verdicts">${rows}</ul>`;
}
function renderEvent(ev) {
  const meta = STAGES[ev.stage] || { zh: ev.stage || '…', en: '' };
  let extra = '';
  if (ev.stage === 'plan' && ev.data) extra = renderPlanCard(ev.data);
  if (ev.stage === 'filter' && ev.data) extra = renderVerdicts(ev.data.verdicts);
  return `<li class="tl-item tl-${esc(ev.stage || 'misc')}${ev.stage === 'done' ? ' tl-done' : ''}">
    <span class="tl-dot"></span>
    <div class="tl-content">
      <div class="tl-meta"><span class="tl-stage">${esc(meta.zh)} ${esc(meta.en)}</span><time class="tl-time">${esc(fmtClock(ev.t))}</time></div>
      ${ev.msg ? `<p class="tl-msg">${esc(ev.msg)}</p>` : ''}
      ${extra}
    </div>
  </li>`;
}

/* ============ render: results (pure) ============ */
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
  const cut = (result.filtered || []).filter((v) => !v.relevant);
  const parts = [];
  parts.push(`<p class="result-summary">找到 <strong>${places.length}</strong> 家 · 深挖 <strong>${reports.length}</strong> 份报告${
    errors.length ? ` · <span class="warn">${errors.length} 个警告</span>` : ''}</p>`);
  if (result.plan) parts.push(renderPlanCard(result.plan));
  if (places.length) {
    parts.push(`<div class="place-list">${places.map((p) => `<button type="button" class="place-row" data-open-place="${esc(p.place_id)}">
      <span class="place-rating">${esc(stars(p.rating))}</span>
      <span class="place-name">${esc(p.name)}</span>
      <span class="place-count">${fmtInt(p.review_count)} 评价</span>
      ${p.address ? `<span class="place-addr">${esc(p.address)}</span>` : ''}
    </button>`).join('')}</div>`);
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

/* ============ render: library (pure) ============ */
function renderShopCard(p, featured) {
  return `<button type="button" class="shop-card${featured ? ' is-featured' : ''}" data-open-place="${esc(p.place_id)}">
    <div class="shop-card-top">
      <span class="shop-rating">${esc(stars(p.rating))}</span>
      ${p.activity_risk ? `<span class="badge badge-risk">${esc(p.activity_risk.severity === 'high' ? '低活跃风险' : '近期偏静')}</span>` : ''}
      ${p.report_count ? `<span class="badge">报告 ×${fmtInt(p.report_count)}</span>` : ''}
    </div>
    <h3 class="shop-name">${esc(p.name)}</h3>
    ${p.category ? `<p class="shop-cat">${esc(p.category)}</p>` : ''}
    <p class="shop-stats"><span>${fmtInt(p.review_count)} 条在列</span><span>${fmtInt(p.cached_reviews)} 条已缓存</span></p>
    ${p.address ? `<p class="shop-addr">${esc(p.address)}</p>` : ''}
    <p class="shop-fresh">更新于 ${esc(relTime(p.last_refreshed))}</p>
  </button>`;
}
function renderLibraryGrid(places) {
  if (!places || !places.length) return '';
  const sorted = [...places].sort((a, b) => (b.cached_reviews || 0) - (a.cached_reviews || 0));
  const featuredCount = sorted.length >= 5 ? 2 : sorted.length >= 3 ? 1 : 0;
  return sorted.map((p, i) => renderShopCard(p, i < featuredCount)).join('');
}
function renderSearchRow(s) {
  // AI-excluded places render struck-through with the verdict reason as tooltip
  const chips = (s.places || [])
    .map((p) => {
      const cut = p.relevant === false;
      const title = cut && p.reason ? ` title="AI 排除：${esc(p.reason)}"` : '';
      return `<button type="button" class="chip chip-link${cut ? ' chip-cut' : ''}"${title}
        data-open-place="${esc(p.place_id)}">${cut ? '✕ ' : ''}${esc(p.name)}</button>`;
    })
    .join('');
  const cutCount = (s.places || []).filter((p) => p.relevant === false).length;
  return `<li class="search-row">
    <div class="search-main">
      <span class="search-query">${esc(s.query)}</span>
      ${s.location ? `<span class="search-loc">@ ${esc(s.location)}</span>` : ''}
      <span class="search-meta">${esc([s.source, cutCount ? `AI 排除 ${cutCount} 家` : '', relTime(s.created_at)].filter(Boolean).join(' · '))}</span>
    </div>
    ${chips ? `<div class="search-places">${chips}</div>` : ''}
  </li>`;
}

/* ============ render: shop detail (pure) ============ */
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
function renderReviewCard(r) {
  const dateStr = typeof r.review_date === 'number' ? relTime(r.review_date) : (r.review_date || '');
  return `<article class="review">
    <header class="review-meta">
      <span class="review-stars">${esc(stars(r.rating))}</span>
      <span class="review-author">${esc(r.author || '匿名')}</span>
      ${dateStr ? `<span class="review-date">${esc(dateStr)}</span>` : ''}
    </header>
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
    ${rep
    ? `<div class="report-meta-line">最新报告${rep.profile ? ` · ${esc(rep.profile)}` : ''}${rep.model ? ` · <span class="model-tag">${esc(rep.model)}</span>` : ''} · ${esc(relTime(rep.created_at))}</div>
       <article class="report"><div class="report-body">${mdToHtml(rep.md)}</div></article>`
    : '<div class="empty small">这家店还没有报告 — 去「单店」跑一份深挖。</div>'}
  </section>
  <section class="detail-section">
    <form class="ask-shop-form" data-place-id="${esc(p.place_id)}">
      <label>只问这家店 <span class="label-en">ask this shop</span></label>
      <div class="ask-inline">
        <input type="text" class="ask-shop-input" autocomplete="off" placeholder="例：他们家能修琴吗？老板态度怎么样？">
        <button type="submit" class="btn-small">问 →</button>
      </div>
    </form>
    <div class="qa-history" data-qa-scope="${esc(p.place_id)}"></div>
    <div class="ask-shop-answer"></div>
  </section>
  <details class="detail-reviews">
    <summary>评价原文 reviews · ${reviews.length} 条</summary>
    <div class="review-list">${reviews.map(renderReviewCard).join('')}</div>
  </details>`;
}

/* ============ jobs: submit + poll (append-only timeline) ============ */
function jobEls(kind) {
  return {
    wrap: $(`#${kind}-job`),
    timeline: $(`#${kind}-timeline`),
    results: $(`#${kind}-results`),
    submit: $(`#${kind}-submit`),
    jobid: $(`#${kind}-jobid`),
  };
}
function setLiveMsg(kind, msg) {
  const el = $(`#${kind}-live .tl-msg`);
  if (el) el.textContent = msg;
}
function removeLive(kind) {
  const el = $(`#${kind}-live`);
  if (el) el.remove();
}
function appendEvents(kind, events) {
  const job = state.jobs[kind];
  if (!job || !Array.isArray(events) || events.length <= job.rendered) return;
  const els = jobEls(kind);
  const html = events.slice(job.rendered).map(renderEvent).join('');
  job.rendered = events.length;
  const live = $(`#${kind}-live`);
  if (live) live.insertAdjacentHTML('beforebegin', html);
  else els.timeline.insertAdjacentHTML('beforeend', html);
  els.timeline.scrollTop = els.timeline.scrollHeight; // auto-scroll timeline only
}
function failJob(kind, msg) {
  const job = state.jobs[kind];
  if (job) job.active = false;
  const els = jobEls(kind);
  els.submit.disabled = false;
  removeLive(kind);
  els.results.innerHTML = errorHtml(msg);
}
async function startJob(kind, path, body) {
  const prev = state.jobs[kind];
  if (prev && prev.timer) clearTimeout(prev.timer);
  if (prev) prev.active = false;
  const job = { id: null, rendered: 0, fails: 0, timer: null, active: true };
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
    job.id = job_id;
    els.jobid.textContent = `job ${job_id}`;
    pollJob(kind); // poll once immediately — cache hits can be instant
  } catch (err) {
    failJob(kind, `提交失败：${err.message} — 确认后端在运行后重试。`);
  }
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
  removeLive(kind);
  if (data.status === 'error') {
    els.results.innerHTML = errorHtml(`任务失败：${data.error || '未知错误'} — 可直接重新提交，已完成的步骤会命中缓存。`);
    return;
  }
  els.results.innerHTML = renderResult(data.result);
  if (state.libraryLoaded) loadLibrary(); // keep library tab fresh in background
}

/* ============ library ============ */
async function loadLibrary() {
  const grid = $('#library-grid');
  const status = $('#library-status');
  const hList = $('#history-list');
  const hStatus = $('#history-status');
  if (!grid.innerHTML) status.innerHTML = loadingHtml('读取资料库');
  const [placesR, searchesR] = await Promise.allSettled([
    apiGet('/api/places'),
    apiGet('/api/searches'),
  ]);
  if (placesR.status === 'fulfilled') {
    state.places = placesR.value || [];
    grid.innerHTML = renderLibraryGrid(state.places);
    status.innerHTML = state.places.length ? '' : emptyHtml('资料库是空的 — 去「侦察」跑第一票。', 'scout');
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

/* ============ shop detail overlay ============ */
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

/* ============ tabs ============ */
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
  if (name === 'library') {
    state.libraryLoaded = true;
    loadLibrary();
  }
  if (name === 'ask') {
    $('#ask-question').focus();
    loadQaHistory(null);
  }
}

/* ============ forms ============ */
function flashInvalid(el) {
  el.classList.add('is-invalid');
  el.focus();
  setTimeout(() => el.classList.remove('is-invalid'), 1200);
}
function submitOnEnter(textarea, form) {
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
}
function bindForms() {
  const scoutForm = $('#scout-form');
  scoutForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const query = $('#scout-query').value.trim();
    if (!query) return flashInvalid($('#scout-query'));
    const body = {
      query,
      top: clampInt($('#scout-top').value, 1, 8, 3),
      max_reviews: clampInt($('#scout-maxr').value, 20, 5000, 300),
    };
    const near = $('#scout-near').value.trim();
    if (near) body.near = near;
    if ($('#scout-profile').value) body.profile = $('#scout-profile').value;
    if ($('#scout-refresh').checked) body.refresh = true;
    if ($('#scout-noai').checked) body.no_ai = true;
    startJob('scout', '/api/scout', body);
  });
  submitOnEnter($('#scout-query'), scoutForm);

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

/* ============ ask: shared runner + QA answer cache ============ */
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
    return `<button type="button" class="chip chip-link" data-ask-again="${esc(r.question)}"
      title="${esc(relTime(r.created_at))} · 点击重问（命中缓存则免费秒回）">${esc(label)}</button>`;
  }).join('');
  return `<div class="qa-chips"><span class="qa-chips-label">问过 asked</span>${chips}</div>`;
}
async function loadQaHistory(placeId) {
  const target = placeId
    ? $(`.qa-history[data-qa-scope="${CSS.escape(placeId)}"]`)
    : $('#ask-history');
  if (!target) return;
  try {
    const rows = await apiGet(`/api/qa${placeId ? `?place_id=${encodeURIComponent(placeId)}` : ''}`);
    target.innerHTML = renderQaChips(rows);
  } catch { /* history is optional decoration */ }
}

/* ============ global delegation & init ============ */
function bindGlobal() {
  document.addEventListener('click', (e) => {
    const tab = e.target.closest('[data-tab]');
    if (tab) return switchTab(tab.dataset.tab);
    const goto = e.target.closest('[data-goto]');
    if (goto) return switchTab(goto.dataset.goto);
    const refresh = e.target.closest('[data-refresh-q]');
    if (refresh) {
      const out = refresh.closest('.answer').parentElement;
      return runAsk(refresh.dataset.refreshQ, refresh.dataset.refreshPlace || null, out, true);
    }
    const again = e.target.closest('[data-ask-again]');
    if (again) {
      const scope = again.closest('.qa-history');
      if (scope) { // scoped re-ask inside the dossier
        const out = scope.parentElement.querySelector('.ask-shop-answer');
        const input = scope.parentElement.querySelector('.ask-shop-input');
        if (input) input.value = again.dataset.askAgain;
        return runAsk(again.dataset.askAgain, scope.dataset.qaScope, out, false);
      }
      $('#ask-question').value = again.dataset.askAgain;
      return runAsk(again.dataset.askAgain, null, $('#ask-answer'), false);
    }
    const del = e.target.closest('[data-delete-place]');
    if (del) return deletePlace(del.dataset.deletePlace, del.dataset.placeName);
    const open = e.target.closest('[data-open-place]');
    if (open) return openDetail(open.dataset.openPlace);
    if (e.target.closest('[data-close]') || e.target.closest('#detail-close')) return closeDetail();
    if (e.target.closest('#library-reload')) return loadLibrary();
    if (e.target.closest('#model-switch')) return toggleModelPicker();
    if (e.target.closest('#model-save')) return saveModel();
  });
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
      el.textContent = `推理 ${m.reason.model} @ ${m.reason.provider} · `
        + `向量 ${m.embed.model} @ ${m.embed.provider} · v${m.version}`;
      $('#model-switch').hidden = false;
    }
  } catch { /* backend offline — footer stays minimal */ }
}

/* ============ model picker — list is LIVE from the provider, never baked in ============ */
const CUSTOM_MODEL = '__custom__';
async function toggleModelPicker() {
  const picker = $('#model-picker');
  if (!picker.hidden) { picker.hidden = true; return; }
  picker.hidden = false;
  const sel = $('#model-select');
  const status = $('#model-status');
  sel.innerHTML = '';
  status.textContent = '实时拉取提供商可用模型…';
  try {
    const res = await apiGet('/api/models');
    for (const name of res.models) {
      sel.appendChild(new Option(name === res.current ? `${name} ← 当前` : name, name));
    }
    sel.appendChild(new Option('自定义手输…', CUSTOM_MODEL));
    if (res.models.includes(res.current)) sel.value = res.current;
    else sel.value = CUSTOM_MODEL;
    status.textContent = res.error
      ? `列表获取失败（仍可手输）：${res.error}`
      : `${res.models.length} 个模型 · 提供商实时列表`;
  } catch (err) {
    sel.appendChild(new Option('自定义手输…', CUSTOM_MODEL));
    sel.value = CUSTOM_MODEL;
    status.textContent = `列表加载失败（仍可手输）：${err.message}`;
  }
  $('#model-custom').hidden = sel.value !== CUSTOM_MODEL;
}
async function saveModel() {
  const sel = $('#model-select');
  const name = (sel.value === CUSTOM_MODEL ? $('#model-custom').value : sel.value).trim();
  const status = $('#model-status');
  if (!name) { status.textContent = '模型名不能为空'; return; }
  const btn = $('#model-save');
  btn.disabled = true;
  status.textContent = `用「${name}」做一次真实冒烟调用…`;
  try {
    await apiPost('/api/settings', { reason_model: name });
    status.textContent = '✓ 已切换并保存 — CLI 与 Web 共用，重启不丢';
    await loadMeta();
    setTimeout(() => { $('#model-picker').hidden = true; status.textContent = ''; }, 2000);
  } catch (err) {
    status.textContent = `✗ 未保存：${err.message}`;
  } finally {
    btn.disabled = false;
  }
}
function init() {
  bindForms();
  bindGlobal();
  switchTab(tabFromHash(), false);
  window.addEventListener('hashchange', () => switchTab(tabFromHash(), false));
  loadProfiles();
  loadMeta();
}
init();

/* debug handle — pure renderers, state, and actions for integration debugging */
window.__pi = {
  state,
  esc, mdToHtml, relTime, stars, fmtClock, safeUrl,
  render: { event: renderEvent, planCard: renderPlanCard, verdicts: renderVerdicts, result: renderResult,
    report: renderReportArticle, libraryGrid: renderLibraryGrid, shopCard: renderShopCard,
    searchRow: renderSearchRow, detail: renderDetail, review: renderReviewCard, hours: renderHours },
  openDetail, closeDetail, switchTab, loadLibrary, startJob,
};
