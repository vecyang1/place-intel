/* placeintel no-build localization and language-state owner. */
'use strict';
(function () {
  const PREF_KEY = 'placeintel.languagePreference';
  const OLD_TX_KEY = 'placeintel.translationTarget';
  const supportedUiLocales = ['en', 'zh'];
  const labels = { en: 'English', zh: '中文', vi: 'Tiếng Việt', ko: '한국어', ja: '日本語', th: 'ไทย', fr: 'Français', es: 'Español', de: 'Deutsch' };
  const commonTargets = ['en', 'zh', 'vi', 'fr', 'es', 'de', 'ko', 'ja', 'th'];
  const messages = {
    en: {
      'skip': 'Skip to main content', 'tagline': 'Read hundreds of reviews before you walk in. Walk in armed.', 'nav.scout': 'Scout', 'nav.shop': 'Shop', 'nav.library': 'Library', 'nav.ask': 'Ask',
      'label.query': 'What are you looking for', 'label.near': 'Where', 'label.profile': 'Report profile', 'label.top': 'Deep-dive count', 'label.max': 'Max reviews', 'label.target': 'Which shop',
      'mode.scout': 'Scout', 'mode.shop': 'Shop', 'mode.ask': 'Ask', 'mode.help.scout': 'Search Maps + fetch reviews', 'mode.help.shop': 'Known shop/link', 'mode.help.ask': 'Cached evidence only',
      'reason.empty': 'Scout searches or refreshes Google Maps and review evidence. Ask only uses cached evidence.', 'advanced': 'Advanced', 'refresh': 'Force refresh cache', 'noai': 'Disable AI planning',
      'button.scout': 'Start Scout →', 'button.shop': 'Deep dive →', 'button.ask': 'Ask cache →', 'hint.scout': 'New places can take a few minutes: plan, search, filter, fetch reviews, embed, then reason. Progress stays visible.',
      'hint.shop': 'The result is a focused report: reputation, recurring complaints, and walk-in guardrails.', 'hint.ask': 'Ask only uses cached evidence. To find or refresh places, run Scout or Shop first.',
      'past.scouts': 'Past scouts', 'refresh.short': 'Refresh ↻', 'live': 'Live progress', 'cached.shops': 'Cached shops', 'past.searches': 'Past searches', 'ask.label': 'Ask all cached reviews',
      'footer': 'placeintel · local review intelligence · data stays on this machine', 'system': 'System', 'model.switch': 'Switch model ⇄', 'model.save': 'Save',
      'detail.title': 'Shop dossier', 'detail.close': 'Close', 'photo.label': 'source photo', 'noscript': 'placeintel needs JavaScript enabled.',
      'ph.query': 'Shop / need / Maps URL, any language\nExample: guitar lessons Da Nang...', 'ph.near': 'Example: Hoi An, Vietnam...', 'ph.shop': 'Example: The Workshop Coffee or a Google Maps link...', 'ph.ask': 'Example: Which teacher is most patient? Any red flags?...', 'ph.model': 'Example: gemini-flash-latest...'
    },
    zh: {
      'skip': '跳到主要内容', 'tagline': '进店之前，先读完它的几百条评价。Walk in armed.', 'nav.scout': '侦察新店 Scout', 'nav.shop': '单店深挖 Shop', 'nav.library': '资料库 Library', 'nav.ask': '问缓存 Ask',
      'label.query': '想找什么', 'label.near': '在哪里', 'label.profile': '报告类型', 'label.top': '深挖几家', 'label.max': '每家最多评价数', 'label.target': '哪家店',
      'mode.scout': '侦察新店 Scout', 'mode.shop': '单店深挖 Shop', 'mode.ask': '问缓存 Ask', 'mode.help.scout': '搜 Maps + 抓评价', 'mode.help.shop': '已知店名/链接', 'mode.help.ask': '只问已有证据',
      'reason.empty': 'Scout 会搜索/刷新 Google Maps 和评价证据；Ask 只问已有缓存证据。', 'advanced': '高级 advanced', 'refresh': '强制刷新缓存', 'noai': '关闭AI规划',
      'button.scout': '开始侦察 Scout →', 'button.shop': '深挖这家店 Deep dive →', 'button.ask': '问缓存 Ask →', 'hint.scout': '第一次跑新地点需要几分钟：AI规划 → 搜索 → AI筛选 → 抓评价 → 向量化 → 推理报告。全程进度都看得见。',
      'hint.shop': '结果是一份聚焦报告：这家店的口碑、反复出现的抱怨、防坑要点。', 'hint.ask': 'Ask 只问已有缓存证据，不搜索 Google Maps。要找新地方或刷新评价，先跑 Scout/Shop。',
      'past.scouts': '已侦察 past scouts', 'refresh.short': '刷新 ↻', 'live': '实时进度 live', 'cached.shops': '已缓存的店 cached shops', 'past.searches': '历史搜索 past searches', 'ask.label': '问缓存里的所有评价',
      'footer': 'placeintel · 本地评价情报站 · 数据只缓存在本机', 'system': '系统 System', 'model.switch': '更换模型 ⇄', 'model.save': '保存',
      'detail.title': '店铺档案 dossier', 'detail.close': '关闭', 'photo.label': 'source photo', 'noscript': 'placeintel 需要启用 JavaScript 才能工作。',
      'ph.query': '店名 / 需求 / Maps URL，任何语言\n例：会安吉他租赁 · guitar lessons Da Nang…', 'ph.near': '例：Hoi An, Vietnam…', 'ph.shop': '例：The Workshop Coffee 或 Google Maps 链接…', 'ph.ask': '例：哪家老师最有耐心？哪家有坑？…', 'ph.model': '例：gemini-flash-latest…'
    },
  };
  const stageLabels = {
    en: { plan: 'plan', search: 'search', filter: 'filter', reviews: 'reviews', embed: 'embed', report: 'report', done: 'done' },
    zh: { plan: 'AI规划 plan', search: '搜索 search', filter: 'AI筛选 filter', reviews: '抓评价 reviews', embed: '向量化 embed', report: '推理报告 report', done: '完成 done' },
  };
  const VI_RE = /[ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]|\b(và|không|nhưng|đẹp|đường|người|nên|khó|rất|chơi|biển|rác|nước|nơi|này|cửa hàng|phục vụ|chất lượng)\b/i;
  const langMetaMap = { zh: ['中文', 'Chinese', 'Chinese-language reviews'], en: ['English', 'EN', 'English-language reviews'], vi: ['Tiếng Việt', 'Vietnamese', 'Vietnamese-language reviews'], ko: ['한국어', 'Korean', 'Korean-language reviews'], ja: ['日本語', 'Japanese', 'Japanese-language reviews'], th: ['ไทย', 'Thai', 'Thai-language reviews'], other: ['Other', 'Other', 'Mixed language'], unknown: ['No text', 'No text', 'Rating-only'] };
  const langOrder = ['zh', 'en', 'vi', 'ko', 'ja', 'th', 'other', 'unknown'];
  const ratingFilters = [['all', 'All ratings', 'all'], ['5', '5★', 'great'], ['4', '4★', 'ok'], ['low', '≤3★', 'issues']];
  const themeRules = [['price', '价格', 'price', /价格|价钱|公道|押金|贵|便宜|price|cost|cheap|expensive|deposit|phí|giá|tiền/i], ['service', '服务/态度', 'service', /服务|老板|态度|helpful|friendly|owner|staff|service|phục vụ|nhân viên|chủ|친절/i], ['quality', '质量/效果', 'quality', /质量|品质|效果|好用|guitar|instrument|quality|selection|đàn|chất lượng|악기/i], ['access', '到达/停车', 'access', /停车|到达|难找|滑|parking|road|access|enter|đường|vào|khó|trượt|leo|주차/i], ['repair', '维修/调琴', 'repair', /修|维修|调琴|调整|repair|setup|action|eq|fix|lắp|chỉnh/i], ['rental', '租赁', 'rental', /租|租赁|rental|rent|hire|thuê/i], ['availability', '选择/库存', 'availability', /选择|库存|现货|available|selection|stock|nhiều|lựa chọn/i], ['crowd', '人流/安静', 'crowd', /人多|排队|拥挤|安静|crowd|busy|quiet|overcrowded|đông|ồn ào/i], ['clean', '清洁/垃圾', 'cleanliness', /干净|垃圾|塑料|clean|trash|plastic|rác|chai nhựa/i], ['view', '景色/氛围', 'view', /漂亮|景色|氛围|view|beautiful|gorgeous|serene|đẹp|trong xanh|mát/i], ['food', '饮食', 'food/drink', /咖啡|椰子|吃|drink|coffee|coconut|food|cafe|nước/i]];
  let prefs = loadPrefs(), serverConfig = null, warned = new Set();
  function normalizeTag(value, allowAuto = false) {
    const aliases = { cn: 'zh', 'zh-cn': 'zh', 'zh-hans': 'zh', chinese: 'zh', english: 'en' };
    if (value == null) return null; let s = String(value).trim().replace(/_/g, '-'); if (!s) return null;
    const low = s.toLowerCase(); if (allowAuto && low === 'auto') return 'auto'; s = aliases[low] || s;
    if (s.length > 35 || /[\x00-\x1f\x7f/\\<>;:'"`{}()[\]|]/.test(s) || !/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$/.test(s)) return null;
    const parts = s.split('-'); return [parts[0].toLowerCase(), ...parts.slice(1).map((p) => p.length === 2 && /^[A-Za-z]+$/.test(p) ? p.toUpperCase() : p.length === 4 && /^[A-Za-z]+$/.test(p) ? p[0].toUpperCase() + p.slice(1).toLowerCase() : p.toLowerCase())].join('-');
  }
  function loadPrefs() { try { const p = JSON.parse(localStorage.getItem(PREF_KEY) || '{}'); const old = localStorage.getItem(OLD_TX_KEY); if (old && !p.translation_target) p.translation_target = old; return p; } catch { return {}; } }
  function savePrefs(next) { prefs = { ...prefs, ...next }; localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); if (prefs.translation_target) localStorage.setItem(OLD_TX_KEY, prefs.translation_target); applyStaticText(); }
  function browserTag() { return normalizeTag((navigator.languages || [navigator.language || 'en'])[0]) || 'en'; }
  function appDefault(key) { return serverConfig?.language?.app_defaults?.[key] || 'auto'; }
  function first(...values) { for (const v of values) { const tag = normalizeTag(v, true); if (tag && tag !== 'auto') return tag; } return null; }
  function activeUi() { const tag = first(prefs.ui_language, appDefault('ui_language'), browserTag()) || 'en'; return supportedUiLocales.includes(tag.split('-')[0]) ? tag.split('-')[0] : 'en'; }
  function outputLanguage(kind = 'answer') { const key = kind === 'report' ? 'report_language' : 'answer_language'; return first(prefs[key], appDefault(key), browserTag()) || 'en'; }
  function translationTarget() { return first(prefs.translation_target, appDefault('translation_target'), outputLanguage('answer')) || 'en'; }
  function t(key, params = {}) { const ui = activeUi(), table = messages[ui] || messages.en; let msg = table[key] ?? messages.en[key]; if (msg == null) { if (!warned.has(key)) { console.warn(`language.locale_missing_key ${key}`); warned.add(key); } msg = key; } return msg.replace(/\{(\w+)\}/g, (_, k) => params[k] ?? ''); }
  function applyStaticText() {
    const ui = activeUi(); document.documentElement.lang = ui;
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.setAttribute('placeholder', t(el.dataset.i18nPlaceholder)); });
    document.querySelectorAll('[data-i18n-aria]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
  }
  function init(config) { if (config) serverConfig = config; applyStaticText(); return state(); }
  function requestPayload(kind) { return { language_hint: browserTag(), report_lang: kind === 'report' ? outputLanguage('report') : outputLanguage('answer') }; }
  function state() { return { ui: activeUi(), answer: outputLanguage('answer'), report: outputLanguage('report'), translationTarget: translationTarget(), browser: browserTag(), prefs }; }
  function relTime(v, toDate) { const d = toDate(v), ui = activeUi(); if (!d) return '—'; const s = (Date.now() - d.getTime()) / 1000; if (s < 0) return new Intl.DateTimeFormat(ui).format(d); const rtf = new Intl.RelativeTimeFormat(ui, { numeric: 'auto' }); if (s < 60) return rtf.format(-Math.floor(s), 'second'); if (s < 3600) return rtf.format(-Math.floor(s / 60), 'minute'); if (s < 86400) return rtf.format(-Math.floor(s / 3600), 'hour'); return s < 86400 * 30 ? rtf.format(-Math.floor(s / 86400), 'day') : new Intl.DateTimeFormat(ui).format(d); }
  function fmtClock(v, toDate) { const d = toDate(v); return d ? new Intl.DateTimeFormat(activeUi(), { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(d) : ''; }
  function fmtInt(n) { return n == null ? '—' : new Intl.NumberFormat(activeUi()).format(Number(n)); }
  function languageOptionsHtml(selected, includeAuto = false) { const opts = includeAuto ? ['auto', ...commonTargets] : commonTargets; return opts.map((tag) => `<option value="${tag}"${selected === tag ? ' selected' : ''}>${tag === 'auto' ? 'Auto' : (labels[tag] || tag)}${tag === 'auto' ? '' : ` · ${tag}`}</option>`).join(''); }
  function stageLabel(stage) { return (stageLabels[activeUi()] || stageLabels.en)[stage] || stage || '...'; }
  function langMeta(code) { return langMetaMap[code] || langMetaMap.other; }
  function reviewBody(r) { return [r.text, r.owner_response].filter(Boolean).join(' '); }
  function detectReviewLang(text) { const s = String(text || '').trim(); if (!s) return 'unknown'; const hit = [[/[\u3400-\u9fff]/, 'zh'], [/[\uac00-\ud7af]/, 'ko'], [/[\u3040-\u30ff]/, 'ja'], [/[\u0e00-\u0e7f]/, 'th'], [VI_RE, 'vi']].find(([re]) => re.test(s)); return hit ? hit[1] : /[a-z]/i.test(s) ? 'en' : 'other'; }
  function reviewThemes(text) { const hits = themeRules.filter((row) => row[3].test(text)).slice(0, 3); return hits.length ? hits : [['general', '整体体验', 'general']]; }
  function reviewRatingBand(rating) { const n = Number(rating); return Number.isFinite(n) && n > 0 ? (n >= 4.5 ? '5' : n >= 3.5 ? '4' : 'low') : 'none'; }
  function languageGroups(reviews) { const groups = new Map(); for (const r of reviews) { const body = reviewBody(r), code = detectReviewLang(body), g = groups.get(code) || { code, count: 0, sum: 0, themes: new Map(), sample: '' }; g.count += 1; g.sum += Number(r.rating) || 0; if (!g.sample && body) g.sample = body.length > 120 ? `${body.slice(0, 120)}…` : body; for (const th of reviewThemes(body)) g.themes.set(th[0], { row: th, count: (g.themes.get(th[0])?.count || 0) + 1 }); groups.set(code, g); } return Array.from(groups.values()).sort((a, b) => (langOrder.indexOf(a.code) - langOrder.indexOf(b.code)) || (b.count - a.count)); }
  window.PI18N = { supportedUiLocales, init, applyConfig: init, applyStaticText, t, normalizeTag, browserTag, state, savePrefs, requestPayload, outputLanguage, translationTarget, labels, languageOptionsHtml, relTime, fmtClock, fmtInt, stageLabel, langMeta, reviewBody, detectReviewLang, reviewThemes, reviewRatingBand, languageGroups, ratingFilters };
}());
