/* placeintel job lifecycle: durable progress via SSE with polling fallback. */
'use strict';

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
