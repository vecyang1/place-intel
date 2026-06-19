/* placeintel dossier enhancements: hi-res media sizing + in-dossier report generation.
   Loaded before app.js so hiRes() is defined before any render; every app.js global it
   uses (state, $, apiGet, apiPost, renderEvent, errorHtml, openDetail, loadLibrary,
   langPayload, clampInt, ui) is referenced only at call time, after app.js has loaded. */
'use strict';

// Bump the size token of Google-hosted photos so cards/lightbox stay sharp on retina + zoom.
// =w400 / =w529-h298-k-no / =s400 → =w<width>; appends when no token; passthrough otherwise.
function hiRes(url, width) {
  const u = String(url || '');
  if (!/^https?:\/\//i.test(u)) return u;
  if (!/googleusercontent\.com|ggpht\.com|gstatic\.com/.test(u)) return u;
  return /=[\w-]+$/.test(u) ? u.replace(/=[\w-]+$/, `=w${width}`) : `${u}=w${width}`;
}

const DOSSIER_POLL_MS = 2000, DOSSIER_MAX_FAILS = 5;

// Generate a report without leaving the dossier: stream live progress into the report slot,
// then refresh the dossier in place. Mirrors streamJob/pollJob but scoped to one inline slot.
async function generateReportInline(btn) {
  const placeId = btn.dataset.generateReport;
  const slot = btn.closest('[data-report-slot]');
  if (!slot || !placeId) return;
  const detailPlace = () => (state.detail && state.detail.place) || {};
  const target = btn.dataset.placeName || detailPlace().name || placeId;
  const near = btn.dataset.placeAddress || detailPlace().address || '';

  slot.innerHTML = `<div class="report-meta-line">${ui('正在生成报告 · 实时进度', 'Generating report · live progress')}</div>`
    + `<ol class="timeline"><li class="tl-item tl-live dossier-live" aria-live="polite"><span class="tl-dot dot-live"></span>`
    + `<div class="tl-content"><p class="tl-msg muted">${ui('已提交，等待后端…', 'Submitted, waiting for backend…')}</p></div></li></ol>`
    + `<div class="job-results" aria-live="polite"></div>`;
  const timeline = slot.querySelector('.timeline'), results = slot.querySelector('.job-results');

  if (state.dossierJob) { try { if (state.dossierJob.es) state.dossierJob.es.close(); } catch (e) { /* already closed */ } clearTimeout(state.dossierJob.timer); }
  const job = { es: null, timer: null, lastId: 0, fails: 0, active: true };
  state.dossierJob = job;
  let jobId = null, rendered = 0;
  // Only touch the DOM while THIS job owns the still-open dossier showing the same place.
  const alive = () => state.dossierJob === job && job.active && !$('#detail-overlay').hidden && detailPlace().place_id === placeId;
  const stop = () => { job.active = false; clearTimeout(job.timer); if (job.es) { try { job.es.close(); } catch (e) { /* noop */ } job.es = null; } if (state.dossierJob === job) state.dossierJob = null; };

  const append = (events) => {
    if (!alive() || !Array.isArray(events) || !events.length) return;
    const fresh = events.filter((ev, i) => (ev.id == null ? i >= rendered : Number(ev.id) > job.lastId));
    if (!fresh.length) return;
    rendered = Math.max(rendered, events.length);
    job.lastId = Math.max(job.lastId, ...fresh.map((ev) => Number(ev.id) || 0));
    const live = timeline.querySelector('.dossier-live'); if (live) live.remove();
    timeline.insertAdjacentHTML('beforeend', fresh.map(renderEvent).join(''));
    timeline.scrollTop = timeline.scrollHeight;
  };

  const pollFinal = async () => {
    if (state.dossierJob !== job || !job.active) return;
    let data;
    try { data = await apiGet(`/api/jobs/${encodeURIComponent(jobId)}`); job.fails = 0; }
    catch (err) {
      job.fails += 1;
      if (job.fails >= DOSSIER_MAX_FAILS) { if (alive()) results.innerHTML = errorHtml(`${ui('轮询失败', 'Polling failed')}：${err.message}`); stop(); return; }
      job.timer = setTimeout(pollFinal, DOSSIER_POLL_MS); return;
    }
    append(data.events || []);
    if (data.status === 'running') { job.timer = setTimeout(pollFinal, DOSSIER_POLL_MS); return; }
    if (job.es) { try { job.es.close(); } catch (e) { /* noop */ } job.es = null; }
    if (data.status === 'error') { if (alive()) results.innerHTML = errorHtml(`${ui('任务失败', 'Job failed')}：${data.error || ui('未知错误', 'unknown error')}`); stop(); return; }
    if (data.status === 'interrupted') { if (alive()) results.innerHTML = errorHtml(`${ui('任务中断', 'Job interrupted')}：${data.retry_hint || data.error || ''}`); stop(); return; }
    const wasAlive = alive();
    stop();
    if (wasAlive) openDetail(placeId);              // refresh the dossier so the new report shows in place
    if (state.libraryLoaded) loadLibrary();         // keep the library card's report badge fresh
  };

  const startStream = () => {
    if (!window.EventSource || !jobId) return pollFinal();
    const es = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events?after=0`); job.es = es;
    es.onmessage = (e) => {
      if (state.dossierJob !== job || !job.active) return es.close();
      try { const ev = JSON.parse(e.data); append([ev]); if (ev.stage === 'done') { es.close(); job.es = null; pollFinal(); } } catch (err) { /* bad frame → final poll */ }
    };
    es.onerror = () => { es.close(); job.es = null; if (state.dossierJob === job && job.active) pollFinal(); };
  };

  const body = { target, max_reviews: clampInt($('#shop-maxr').value, 20, 5000, 300), refresh: false, ...langPayload('report') };
  if (near) body.near = near;
  if ($('#shop-profile').value) body.profile = $('#shop-profile').value;
  try {
    const res = await apiPost('/api/shop', body);
    if (state.dossierJob !== job || !job.active) return;   // dossier closed while POST was in flight
    jobId = res.job_id;
    startStream();
  } catch (err) {
    if (alive()) results.innerHTML = errorHtml(`${ui('提交失败', 'Submit failed')}：${err.message}`);
    stop();
  }
}
