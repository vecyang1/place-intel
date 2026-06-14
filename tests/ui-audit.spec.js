import { test, expect } from '@playwright/test';

test('home has no console errors, no horizontal overflow, and visible first action', async ({ page }) => {
  const messages = [];
  page.on('console', (msg) => messages.push(`${msg.type()}: ${msg.text()}`));
  page.on('pageerror', (err) => messages.push(`pageerror: ${err.message}`));

  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });

  const metrics = await page.evaluate(() => {
    const button = document.querySelector('#scout-submit');
    const textarea = document.querySelector('#scout-query');
    const doc = document.documentElement;
    const s = getComputedStyle(button);
    const t = getComputedStyle(textarea, '::placeholder');
    return {
      overflow: doc.scrollWidth - doc.clientWidth,
      buttonBg: s.backgroundColor,
      buttonColor: s.color,
      placeholderColor: t.color,
      textareaHeight: textarea.getBoundingClientRect().height,
      buttonHeight: button.getBoundingClientRect().height,
    };
  });

  expect(messages.filter((m) => m.startsWith('error:') || m.startsWith('pageerror:'))).toEqual([]);
  expect(metrics.overflow).toBeLessThanOrEqual(0);
  expect(metrics.textareaHeight).toBeGreaterThanOrEqual(105);
  expect(metrics.buttonHeight).toBeGreaterThanOrEqual(44);
  expect(metrics.buttonBg).not.toBe('rgba(0, 0, 0, 0)');
  expect(metrics.placeholderColor).not.toBe('rgba(0, 0, 0, 0)');
});

test('command center recommends shop for Maps links and starts Shop from the first input', async ({ page }) => {
  let shopBody = null;
  await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/shop', (route) => {
    shopBody = route.request().postDataJSON();
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ job_id: 'job-shop' }) });
  });
  await page.route('**/api/jobs/job-shop/events*', (route) => route.fulfill({ status: 204, body: '' }));
  await page.route('**/api/jobs/job-shop', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ status: 'done', events: [], result: { query: 'DClass', mode: 'single', places: [], reports: [], errors: [] } }),
  }));

  await page.goto('http://127.0.0.1:9618/#scout', { waitUntil: 'networkidle' });
  await page.locator('#scout-query').fill('https://www.google.com/maps/place/DClass+Guitar');

  await expect(page.locator('[data-command-mode="shop"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#command-reason')).toContainText('Maps');
  await page.locator('#scout-submit').click();

  expect(shopBody).toMatchObject({ target: 'https://www.google.com/maps/place/DClass+Guitar' });
  await expect(page.locator('#tab-shop')).toHaveAttribute('aria-selected', 'true');
});

test('command center manual Ask override answers from the first input', async ({ page }) => {
  const askBodies = [];
  await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/ask', (route) => {
    askBodies.push(route.request().postDataJSON());
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ answer: '缓存证据显示押金需要现场确认。', cached: false, model: 'test-model', provider: 'test' }),
    });
  });

  await page.goto('http://127.0.0.1:9618/#scout', { waitUntil: 'networkidle' });
  await page.locator('#scout-query').fill('押金怎么收？');
  await page.locator('[data-command-mode="ask"]').click();
  await page.locator('#scout-submit').click();

  expect(askBodies.at(-1)).toMatchObject({ question: '押金怎么收？' });
  await expect(page.locator('#tab-ask')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#ask-answer')).toContainText('押金需要现场确认');
});

test('command center reuses matching fresh scout history instead of submitting a duplicate scrape', async ({ page }) => {
  let scoutRequests = 0;
  await page.route('**/api/searches', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 8, query: 'Hoi An guitar rental', location: 'Hoi An', source: 'scout',
      created_at: Date.now() / 1000 - 1800,
      places: [{ place_id: 'dclass', name: "D'Class Guitar", relevant: true }],
    }]),
  }));
  await page.route('**/api/scout', (route) => { scoutRequests += 1; return route.fulfill({ status: 500, body: 'duplicate' }); });

  await page.goto('http://127.0.0.1:9618/#scout', { waitUntil: 'networkidle' });
  await page.locator('#scout-query').fill('Hoi An guitar rental');
  await page.locator('#scout-near').fill('Hoi An');
  await page.locator('#scout-submit').click();

  expect(scoutRequests).toBe(0);
  await expect(page.locator('#scout-past-status')).toContainText('缓存');
  await expect(page.locator('#scout-past-list')).toContainText("D'Class Guitar");
});

test('scout tab shows past scouts below the form to avoid duplicate work', async ({ page }) => {
  await page.route('**/api/searches', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 7,
      query: 'Hoi An guitar rental',
      location: 'Hoi An',
      source: 'cache',
      created_at: Date.now() / 1000 - 3600,
      places: [
        { place_id: 'dclass', name: "D'Class Guitar Hội An", relevant: true },
        ...Array.from({ length: 9 }, (_, i) => ({ place_id: `kept-${i}`, name: `Candidate ${i + 1}`, relevant: true })),
        { place_id: 'taxi', name: 'HoiAnGO E-Taxi', relevant: false, reason: 'not a guitar shop' },
      ],
    }]),
  }));

  await page.goto('http://127.0.0.1:9618/#scout', { waitUntil: 'networkidle' });

  await expect(page.locator('#scout-past')).toBeVisible();
  await expect(page.locator('#scout-past-title')).toContainText('已侦察');
  await expect(page.locator('#scout-past-list .search-row')).toHaveCount(1);
  await expect(page.locator('#scout-past-list')).toContainText('Hoi An guitar rental');
  await expect(page.locator('#scout-past-list .search-meta')).toContainText('AI 排除 1 家');
  await expect(page.locator('#scout-past-list [data-open-place="dclass"]')).toContainText("D'Class Guitar");
  await expect(page.locator('#scout-past-list .search-places .chip')).toHaveCount(9);
  await expect(page.locator('#scout-past-list .chip-more')).toContainText('+2 家');
  await expect(page.locator('#scout-past-list [data-open-place="taxi"]')).toHaveCount(0);
  await expect(page.locator('#scout-past-list .chip-cut')).toHaveCount(0);
});

test('scout results explain plan, verdicts, deep dives, timeline groups, and compare picks', async ({ page }) => {
  const plan = {
    intent: 'rent a guitar before walking in',
    queries: ['guitar rental Hoi An', '会安 吉他租赁'],
    near: 'Hoi An',
    profile: 'rental',
    report_lang: 'zh',
    reasoning: 'Use bilingual searches because travelers and local shops describe rental differently.',
  };
  await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/scout', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ job_id: 'job-ui2' }) }));
  await page.route('**/api/jobs/job-ui2/events*', (route) => route.fulfill({ status: 204, body: '' }));
  await page.route('**/api/jobs/job-ui2', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'done',
      events: [
        { id: 1, t: Date.now() / 1000, stage: 'plan', msg: 'AI planned bilingual searches.', data: plan },
        { id: 2, t: Date.now() / 1000, stage: 'filter', msg: 'AI kept 2 and excluded 1.', data: { verdicts: [
          { place_id: 'dclass', name: "D'Class Guitar", relevant: true, reason: 'direct guitar rental evidence' },
          { place_id: 'taxi', name: 'HoiAnGO E-Taxi', relevant: false, reason: 'transport company, not instrument rental' },
        ] } },
        { id: 3, t: Date.now() / 1000, stage: 'reviews', msg: '缓存命中 cache hit for DClass' },
        { id: 4, t: Date.now() / 1000, stage: 'report', msg: '重试 retry 1/3 after provider timeout' },
      ],
      result: {
        query: 'Hoi An guitar rental',
        location: 'Hoi An',
        profile: 'rental',
        plan,
        places: [
          { place_id: 'dclass', name: "D'Class Guitar", rating: 4.9, review_count: 149, address: 'Hoi An old town' },
          { place_id: 'hero', name: 'Hero Guitar', rating: 4.7, review_count: 20, address: 'Cam Chau' },
        ],
        filtered: [
          { place_id: 'dclass', name: "D'Class Guitar", relevant: true, reason: 'direct guitar rental evidence' },
          { place_id: 'hero', name: 'Hero Guitar', relevant: true, reason: 'music shop candidate' },
          { place_id: 'taxi', name: 'HoiAnGO E-Taxi', relevant: false, reason: 'transport company, not instrument rental' },
        ],
        reports: [{ place_id: 'dclass', name: "D'Class Guitar", md: '# Report\n\nWalk in with rental questions.' }],
        errors: [],
      },
    }),
  }));

  await page.goto('http://127.0.0.1:9618/#scout', { waitUntil: 'networkidle' });
  await page.locator('#scout-query').fill('Hoi An guitar rental');
  await page.locator('#scout-submit').click();

  await expect(page.locator('#scout-results .plan-card')).toContainText('rent a guitar');
  await expect(page.locator('#scout-results .plan-card')).toContainText('guitar rental Hoi An');
  await expect(page.locator('#scout-results .plan-card')).toContainText('会安 吉他租赁');
  await expect(page.locator('#scout-results .plan-card')).toContainText('Hoi An');
  await expect(page.locator('#scout-results .plan-card')).toContainText('rental');
  await expect(page.locator('#scout-results .verdict-reason.chip')).toHaveCount(3);
  await expect(page.locator('#scout-results .verdict.is-cut .verdict-reason')).toContainText('transport company');
  await expect(page.locator('#scout-results [data-open-place="dclass"]')).toHaveClass(/is-deep/);
  await expect(page.locator('#scout-results [data-open-place="hero"]')).not.toHaveClass(/is-deep/);
  await expect(page.locator('#scout-timeline .tl-cache')).toContainText('cache hit');
  await expect(page.locator('#scout-timeline .tl-retry')).toContainText('retry');

  const compare = page.locator('#scout-results [data-compare-place="dclass"]');
  await expect(compare).toHaveAttribute('aria-pressed', 'false');
  await compare.click();
  await expect(compare).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#scout-results #compare-tray')).toContainText("D'Class");
  await expect(page.locator('#detail-overlay')).toBeHidden();
});

test('library search filters cached shops and caps the initial list', async ({ page }) => {
  const now = Date.now() / 1000;
  const places = Array.from({ length: 14 }, (_, i) => ({
    place_id: `place-${i}`, name: `Scenic Place ${i}`, category: 'Scenic spot',
    rating: 4 + (i % 5) / 10, review_count: 100 + i, cached_reviews: 10 + i,
    address: `Road ${i}, Da Nang`, last_refreshed: now - i * 3600,
    report_count: i === 4 ? 1 : 0,
  }));
  Object.assign(places[0], { name: 'Fresh Scenic Pier', last_refreshed: now + 60 });
  Object.assign(places[1], { name: 'Cached Giant View', rating: 4.1, cached_reviews: 500, last_refreshed: now - 86400 });
  Object.assign(places[2], { name: 'Five Star Peak', rating: 5, cached_reviews: 12, last_refreshed: now - 7200 });
  places.push({ place_id: 'guitar-shop', name: "D'Class Guitar Hội An", category: 'Musical instrument store', rating: 4.9, review_count: 149, cached_reviews: 149, address: 'Hoi An', last_refreshed: now - 7200, report_count: 3 });
  await page.route('**/api/places', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(places) }));
  await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));

  await page.goto('http://127.0.0.1:9618/#library', { waitUntil: 'networkidle' });

  await expect(page.locator('#library-search')).toBeVisible();
  await expect(page.locator('#library-sort')).toHaveValue('smart');
  await expect(page.locator('#library-grid .shop-card')).toHaveCount(12);
  await expect(page.locator('#library-grid .shop-card').first()).toContainText("D'Class Guitar");
  await expect(page.locator('[data-library-more]')).toContainText('显示更多');
  await page.locator('[data-library-more]').click();
  await expect(page.locator('#library-grid .shop-card')).toHaveCount(15);
  await expect(page.locator('[data-library-more]')).toHaveCount(0);
  await page.locator('#library-sort').selectOption('fresh');
  await expect(page.locator('#library-grid .shop-card')).toHaveCount(12);
  await expect(page.locator('#library-grid .shop-card').first()).toContainText('Fresh Scenic Pier');
  await page.locator('#library-sort').selectOption('cached');
  await expect(page.locator('#library-grid .shop-card').first()).toContainText('Cached Giant View');
  await page.locator('#library-sort').selectOption('rating');
  await expect(page.locator('#library-grid .shop-card').first()).toContainText('Five Star Peak');
  await page.locator('#library-search').fill('guitar');
  await expect(page.locator('#library-grid .shop-card')).toHaveCount(1);
  await expect(page.locator('#library-grid')).toContainText("D'Class Guitar");
  await expect(page.locator('#library-status')).toContainText('显示 1 / 15');
});

test('library workspace filters decision signals and opens compare', async ({ page }) => {
  const now = Date.now() / 1000;
  const places = [
    {
      place_id: 'guitar-shop', name: "D'Class Guitar Hội An", category: 'Musical instrument store',
      rating: 4.9, review_count: 149, cached_reviews: 149, address: 'Hoi An',
      last_refreshed: now - 7200, report_count: 3, latest_report_at: now - 600,
      latest_report_profile: 'rental', favorite: true, language_cohorts: [{ lang: 'zh' }, { lang: 'en' }],
    },
    {
      place_id: 'quiet-tour', name: 'Quiet Lantern Tour', category: 'Tour operator',
      rating: 4.2, review_count: 220, cached_reviews: 40, address: 'Cam Nam',
      last_refreshed: now - 30 * 86400, report_count: 0, languages: ['vi'],
      activity_risk: { severity: 'high', label: 'possible low activity', reason: 'latest known reviews are stale' },
    },
    {
      place_id: 'tiny-cafe', name: 'Tiny Cafe', category: 'Cafe',
      rating: 4.6, review_count: 12, cached_reviews: 5, address: 'Old town',
      last_refreshed: now - 3600, report_count: 0, languages: ['ko'],
    },
  ];
  await page.route('**/api/places', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(places) }));
  await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));

  await page.goto('http://127.0.0.1:9618/#library', { waitUntil: 'networkidle' });

  for (const id of ['#library-category', '#library-freshness', '#library-risk', '#library-language', '#library-cached', '#library-report']) {
    await expect(page.locator(id)).toBeVisible();
  }
  const guitarCard = page.locator('#library-grid .shop-card').filter({ hasText: "D'Class Guitar" });
  await expect(guitarCard).toContainText('最近报告');
  await expect(guitarCard).toContainText('rental');
  await expect(page.locator('[data-favorite-place="guitar-shop"]')).toHaveText('已收藏');

  await page.locator('#library-category').selectOption('Musical instrument store');
  await page.locator('#library-language').selectOption('zh');
  await page.locator('#library-cached').selectOption('100');
  await page.locator('#library-report').selectOption('rental');
  await expect(page.locator('#library-grid .shop-card')).toHaveCount(1);
  await expect(page.locator('#library-grid')).toContainText("D'Class Guitar");

  await page.locator('#library-category').selectOption('');
  await page.locator('#library-language').selectOption('');
  await page.locator('#library-cached').selectOption('');
  await page.locator('#library-report').selectOption('');
  await page.locator('#library-risk').selectOption('risk');
  await expect(page.locator('#library-grid .shop-card')).toHaveCount(1);
  await expect(page.locator('#library-grid')).toContainText('Quiet Lantern Tour');
  await page.locator('#library-freshness').selectOption('stale');
  await expect(page.locator('#library-grid')).toContainText('Quiet Lantern Tour');

  await page.locator('#library-risk').selectOption('');
  await page.locator('#library-freshness').selectOption('');
  await page.locator('[data-library-compare="guitar-shop"]').click();
  await page.locator('[data-library-compare="quiet-tour"]').click();
  await expect(page.locator('#library-compare')).toContainText('Compare 2/5');
  await expect(page.locator('#library-compare')).toContainText("D'Class Guitar");
  await expect(page.locator('#library-compare')).toContainText('Quiet Lantern Tour');
  await page.locator('[data-library-compare-clear]').click();
  await expect(page.locator('#library-compare')).toContainText('选择 2-5 家');
});

test('library favorite toggle posts state and rerenders without opening dossier', async ({ page }) => {
  const now = Date.now() / 1000;
  let favorite = false;
  const requests = [];
  await page.route('**/api/places', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([{
      place_id: 'guitar-shop', name: "D'Class Guitar Hội An",
      category: 'Musical instrument store', rating: 4.9, review_count: 149,
      cached_reviews: 149, address: 'Hoi An', last_refreshed: now,
      report_count: 3, favorite, refresh_enabled: false,
    }]),
  }));
  await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/places/guitar-shop/favorite', async (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    favorite = body.favorite;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ place_id: 'guitar-shop', favorite, refresh_enabled: false }) });
  });

  await page.goto('http://127.0.0.1:9618/#library', { waitUntil: 'networkidle' });
  const fav = page.locator('[data-favorite-place="guitar-shop"]');

  await expect(fav).toHaveAttribute('aria-pressed', 'false');
  await fav.click();

  expect(requests).toEqual([{ favorite: true }]);
  await expect(fav).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#detail-overlay')).toBeHidden();
});

test('dossier delete closes modal and rerenders library from API state', async ({ page }) => {
  const now = Date.now() / 1000;
  let deleted = false;
  const place = {
    place_id: 'delete-me', name: 'Delete Me Guitar', category: 'Instrument store',
    rating: 4.7, review_count: 50, cached_reviews: 20, address: 'Hoi An',
    last_refreshed: now, favorite: false, refresh_enabled: false,
  };
  page.on('dialog', (dialog) => dialog.accept());
  await page.route('**/api/places', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify(deleted ? [] : [place]),
  }));
  await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/places/delete-me', (route) => {
    if (route.request().method() === 'DELETE') {
      deleted = true;
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ deleted: 'delete-me' }) });
    }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ place, reviews: [], report: null }) });
  });

  await page.goto('http://127.0.0.1:9618/#library', { waitUntil: 'networkidle' });
  await page.locator('[data-open-place="delete-me"]').click();
  await expect(page.locator('[data-delete-place="delete-me"]')).toBeVisible();
  await page.locator('[data-delete-place="delete-me"]').click();

  expect(deleted).toBe(true);
  await expect(page.locator('#detail-overlay')).toBeHidden();
  await expect(page.locator('#library-status')).toContainText('资料库是空的');
});

test('activity risk renders as a cautious visible tag', async ({ page }) => {
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });
  const html = await page.evaluate(() => {
    const place = {
      place_id: 'synthetic-stale',
      name: 'Synthetic Stale Cafe',
      category: 'Cafe',
      rating: 4.6,
      review_count: 240,
      cached_reviews: 120,
      last_refreshed: Date.now() / 1000,
      activity_risk: {
        severity: 'high',
        label: '可能已停业/低活跃',
        reason: '历史评价很多，但最近没有新评价；出发前应核实仍在营业。',
      },
    };
    return [
      window.__pi.render.shopCard(place, false),
      window.__pi.render.detail({ place, reviews: [], report: null }),
    ].join('\n');
  });

  expect(html).toContain('badge-risk');
  expect(html).toContain('低活跃风险');
  expect(html).toContain('activity-risk');
  expect(html).toContain('出发前应核实仍在营业');
});

test('shop dossier keeps the scoped ask form above the report body', async ({ page }) => {
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });
  const order = await page.evaluate(() => {
    const place = {
      place_id: 'layout-test',
      name: 'Layout Test Guitar',
      category: 'Musical instrument store',
      rating: 4.9,
      review_count: 16,
      cached_reviews: 16,
      last_refreshed: Date.now() / 1000,
    };
    const host = document.createElement('div');
    host.innerHTML = window.__pi.render.detail({
      place,
      reviews: [],
      report: {
        profile: 'lessons',
        model: 'test-model',
        created_at: Date.now() / 1000,
        md: '# 店铺报告\n\n很长的报告正文。',
      },
    });
    const ask = host.querySelector('.ask-shop-form');
    const report = host.querySelector('.report');
    return {
      askBeforeReport: Boolean(ask.compareDocumentPosition(report) & Node.DOCUMENT_POSITION_FOLLOWING),
      firstSectionHasAsk: Boolean(host.querySelector('.detail-shop + .detail-section .ask-shop-form')),
      scopedPlace: ask.dataset.placeId,
    };
  });

  expect(order).toEqual({
    askBeforeReport: true,
    firstSectionHasAsk: true,
    scopedPlace: 'layout-test',
  });
});

test('shop dossier segments reviews by language and filters raw comments', async ({ page }) => {
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    const place = {
      place_id: 'language-test',
      name: 'Language Test Shop',
      category: 'Instrument store',
      rating: 4.8,
      review_count: 4,
      cached_reviews: 4,
      last_refreshed: Date.now() / 1000,
    };
    const reviews = [{
      rating: 5,
      author: 'Chen',
      review_date: Date.now() / 1000,
      text: '价格公道，老板会调琴，也可以租吉他练习。',
    }, {
      rating: 4,
      author: 'Grace',
      review_date: Date.now() / 1000,
      text: 'Helpful owner, fair rental price, and a good selection of guitars.',
    }, {
      rating: 4,
      author: 'Minh',
      review_date: Date.now() / 1000,
      text: 'Đường vào hơi khó nhưng cửa hàng phục vụ tốt và đàn chất lượng.',
    }, {
      rating: 3,
      author: 'Kim',
      review_date: Date.now() / 1000,
      text: '주차가 어렵지만 직원은 친절했어요.',
    }];
    document.body.insertAdjacentHTML('beforeend', `<div id="lang-host">${window.__pi.render.detail({
      place,
      reviews,
      report: null,
    })}</div>`);
    document.querySelector('#lang-host .detail-reviews').open = true;
  });

  await expect(page.locator('.language-lens')).toContainText('语言视角');
  await expect(page.locator('.language-filters')).toBeVisible();
  await expect(page.locator('.language-grid')).toBeHidden();
  await expect(page.locator('.review[data-review-lang="zh"]')).toBeVisible();

  await page.locator('.language-insights > summary').click();
  await expect(page.locator('[data-review-lang-card="zh"]')).toContainText('中文');
  await expect(page.locator('[data-review-lang-card="en"]')).toContainText('English');
  await expect(page.locator('[data-review-lang-card="vi"]')).toContainText('Tiếng Việt');
  await expect(page.locator('[data-review-lang-card="ko"]')).toContainText('Korean');
  await expect(page.locator('.language-lens')).toContainText('价格');
  await expect(page.locator('.language-lens')).toContainText('到达');

  await expect(page.locator('.rating-filters')).toBeVisible();
  await expect(page.locator('[data-review-rating-filter="low"]')).toContainText('≤3★');
  await page.locator('[data-review-rating-filter="low"]').click();
  await expect(page.locator('.review[data-review-lang="ko"]')).toBeVisible();
  await expect(page.locator('.review[data-review-lang="zh"]')).toBeHidden();
  await expect(page.locator('.review-filter-count')).toContainText('显示 1 / 4');

  await page.locator('[data-review-lang-filter="en"]').click();
  await expect(page.locator('.review[data-review-lang="en"]')).toBeHidden();
  await expect(page.locator('.review[data-review-lang="zh"]')).toBeHidden();
  await expect(page.locator('.review-filter-count')).toContainText('显示 0 / 4');

  await page.locator('[data-review-rating-filter="all"]').click();
  await expect(page.locator('.review[data-review-lang="en"]')).toBeVisible();
  await expect(page.locator('.review-filter-count')).toContainText('显示 1 / 4');

  await page.locator('[data-review-lang-filter="all"]').click();
  await expect(page.locator('.review[data-review-lang="zh"]')).toBeVisible();
  await expect(page.locator('.review-filter-count')).toContainText('显示全部 4');
});

test('review translate click translates all visible comments on demand', async ({ page }) => {
  const translateBodies = [];
  await page.route('**/api/reviews/translate', (route) => {
    const body = route.request().postDataJSON();
    translateBodies.push(body);
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        review_id: body.review_id,
        target_lang: body.target_lang,
        source_lang: body.review_id.includes('en') ? 'en' : 'vi',
        text: body.review_id.includes('en') ? '老板很热情，价格透明。' : '通往这里的路有点难走，但景色很漂亮。',
        cached: false,
        model: 'gemini-3.1-flash-lite',
        provider: 'test-provider',
        created_at: Date.now() / 1000,
      }),
    });
  });
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    const place = { place_id: 'translate-test', name: 'Translate Test', rating: 4.8, review_count: 2 };
    const reviews = [
      { review_id: 'review-vi-1', rating: 5, author: 'Minh', text: 'Đường vào hơi khó nhưng cảnh rất đẹp.', lang: 'vi' },
      { review_id: 'review-en-1', rating: 5, author: 'Grace', text: 'Helpful owner and transparent prices.', lang: 'en' },
    ];
    document.body.insertAdjacentHTML('beforeend', `<div id="translate-host">${window.__pi.render.detail({ place, reviews, report: null })}</div>`);
    document.querySelector('#translate-host .detail-reviews').open = true;
  });

  await expect(page.locator('#translate-host .review-translation')).toHaveCount(0);
  const button = page.locator('[data-review-translate="review-vi-1"]');
  await expect(button).toBeVisible();
  await button.click();
  await expect(page.locator('#translate-host .review-translation')).toHaveCount(2);
  await expect(page.locator('#translate-host .review-translation')).toContainText(['通往这里的路有点难走', '老板很热情']);
  await expect(page.locator('#translate-host [data-review-translate="review-vi-1"]')).toContainText('已译');
  await expect(page.locator('#translate-host [data-review-translate="review-en-1"]')).toContainText('已译');
  expect(translateBodies).toEqual([
    { review_id: 'review-vi-1', target_lang: 'zh' },
    { review_id: 'review-en-1', target_lang: 'zh' },
  ]);
});

test('review translation respects combined rating and language filters', async ({ page }) => {
  const translateBodies = [];
  await page.route('**/api/reviews/translate', (route) => {
    const body = route.request().postDataJSON();
    translateBodies.push(body);
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ review_id: body.review_id, target_lang: body.target_lang, source_lang: 'en', text: '低分原因：停车困难，员工态度差。', cached: false, model: 'gemini-3.1-flash-lite', provider: 'test-provider', created_at: Date.now() / 1000 }),
    });
  });
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    const place = { place_id: 'filtered-translate-test', name: 'Filtered Translate Test', rating: 3.8, review_count: 3 };
    const reviews = [
      { review_id: 'review-low-en', rating: 2, author: 'Grace', text: 'Bad parking and rude staff.', lang: 'en' },
      { review_id: 'review-high-en', rating: 5, author: 'Sam', text: 'Helpful owner and transparent prices.', lang: 'en' },
      { review_id: 'review-low-vi', rating: 2, author: 'Minh', text: 'Đường vào khó và chỗ đậu xe tệ.', lang: 'vi' },
    ];
    document.body.insertAdjacentHTML('beforeend', `<div id="filtered-translate-host">${window.__pi.render.detail({ place, reviews, report: null })}</div>`);
    document.querySelector('#filtered-translate-host .detail-reviews').open = true;
  });

  await page.locator('#filtered-translate-host [data-review-rating-filter="low"]').click();
  await page.locator('#filtered-translate-host [data-review-lang-filter="en"]').click();
  await expect(page.locator('#filtered-translate-host .review-filter-count')).toContainText('显示 1 / 3');
  await page.locator('#filtered-translate-host [data-review-translate="review-low-en"]').click();
  await expect(page.locator('#filtered-translate-host .review-translation')).toHaveCount(1);
  expect(translateBodies).toEqual([{ review_id: 'review-low-en', target_lang: 'zh' }]);
});

test('review translation target is configurable and remembered', async ({ page }) => {
  const translateBodies = [];
  await page.route('**/api/reviews/translate', (route) => {
    const body = route.request().postDataJSON();
    translateBodies.push(body);
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        review_id: body.review_id,
        target_lang: body.target_lang,
        source_lang: 'vi',
        text: 'The road is a little hard, but the view is beautiful.',
        cached: false,
        model: 'gemini-3.1-flash-lite',
        provider: 'test-provider',
        created_at: Date.now() / 1000,
      }),
    });
  });
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    localStorage.removeItem('placeintel.translationTarget');
    const place = { place_id: 'translate-target-test', name: 'Translate Target Test', rating: 4.8, review_count: 1 };
    const reviews = [{ review_id: 'review-vi-target', rating: 5, author: 'Minh', text: 'Đường vào hơi khó nhưng cảnh rất đẹp.', lang: 'vi' }];
    document.body.insertAdjacentHTML('beforeend', `<div id="translate-target-host">${window.__pi.render.detail({ place, reviews, report: null })}</div>`);
    document.querySelector('#translate-target-host .detail-reviews').open = true;
  });

  const target = page.locator('#translate-target-host .translation-target');
  await expect(target).toHaveValue('zh');
  await target.selectOption('en');
  await expect(page.locator('#translate-target-host [data-review-translate="review-vi-target"]')).toContainText('EN');
  await expect(page.evaluate(() => localStorage.getItem('placeintel.translationTarget'))).resolves.toBe('en');
  await page.locator('#translate-target-host [data-review-translate="review-vi-target"]').click();
  await expect(page.locator('#translate-target-host .review-translation')).toContainText('The road is a little hard');
  expect(translateBodies).toEqual([{ review_id: 'review-vi-target', target_lang: 'en' }]);
});

test('review translation batch blocks duplicate clicks and stale target responses', async ({ page }) => {
  const translateBodies = [];
  let releaseZh;
  const zhGate = new Promise((resolve) => { releaseZh = resolve; });
  await page.route('**/api/reviews/translate', async (route) => {
    const body = route.request().postDataJSON();
    translateBodies.push(body);
    if (body.target_lang === 'zh') await zhGate;
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        review_id: body.review_id,
        target_lang: body.target_lang,
        source_lang: 'vi',
        text: body.target_lang === 'en' ? `Fresh English ${body.review_id}` : `旧中文 ${body.review_id}`,
        cached: false,
        model: 'gemini-3.1-flash-lite',
        provider: 'test-provider',
        created_at: Date.now() / 1000,
      }),
    });
  });
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    localStorage.removeItem('placeintel.translationTarget');
    const place = { place_id: 'translate-race-test', name: 'Translate Race Test', rating: 4.8, review_count: 4 };
    const reviews = [1, 2, 3, 4].map((n) => ({ review_id: `review-race-${n}`, rating: 5, author: `Guest ${n}`, text: `Đường vào hơi khó nhưng cảnh rất đẹp ${n}.`, lang: 'vi' }));
    document.body.insertAdjacentHTML('beforeend', `<div id="translate-race-host">${window.__pi.render.detail({ place, reviews, report: null })}</div>`);
    document.querySelector('#translate-race-host .detail-reviews').open = true;
  });

  await page.locator('#translate-race-host [data-review-translate="review-race-1"]').click();
  await expect(page.locator('#translate-race-host [data-review-translate="review-race-4"]')).toBeDisabled();
  await page.evaluate(() => document.querySelector('#translate-race-host [data-review-translate="review-race-4"]').click());
  await expect.poll(() => translateBodies.length).toBe(3);
  await page.evaluate(() => {
    const sel = document.querySelector('#translate-race-host .translation-target');
    sel.value = 'en';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  });
  releaseZh();
  await page.waitForTimeout(100);
  await expect(page.locator('#translate-race-host .review-translation')).toHaveCount(0);
  await expect(page.locator('#translate-race-host [data-review-translate="review-race-1"]')).toContainText('EN');
  await page.locator('#translate-race-host [data-review-translate="review-race-1"]').click();
  await expect(page.locator('#translate-race-host .review-translation')).toHaveCount(4);
  expect(translateBodies.filter((body) => body.target_lang === 'zh')).toHaveLength(3);
  expect(translateBodies.filter((body) => body.target_lang === 'en')).toHaveLength(4);
});

test('review translation can retry after a transient failure', async ({ page }) => {
  let attempts = 0;
  await page.route('**/api/reviews/translate', (route) => {
    attempts += 1;
    if (attempts === 1) {
      return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'temporary outage' }) });
    }
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        review_id: 'review-en-1',
        target_lang: 'zh',
        source_lang: 'en',
        text: '老板很热情，价格也透明。',
        cached: false,
        model: 'test-model',
        provider: 'test-provider',
        created_at: Date.now() / 1000,
      }),
    });
  });
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    const place = { place_id: 'translate-retry-test', name: 'Translate Retry Test', rating: 4.8, review_count: 1 };
    const reviews = [{ review_id: 'review-en-1', rating: 5, author: 'Grace', text: 'Helpful owner and transparent prices.', lang: 'en' }];
    document.body.insertAdjacentHTML('beforeend', `<div id="translate-retry-host">${window.__pi.render.detail({ place, reviews, report: null })}</div>`);
    document.querySelector('#translate-retry-host .detail-reviews').open = true;
  });

  const button = page.locator('[data-review-translate="review-en-1"]');
  await button.click();
  await expect(page.locator('#translate-retry-host .review-translation.is-error')).toContainText('temporary outage');
  await button.click();
  await expect(page.locator('#translate-retry-host .review-translation')).toContainText('老板很热情');
  await expect(page.locator('#translate-retry-host .review-translation.is-error')).toHaveCount(0);
  await expect(button).toContainText('已译');
  expect(attempts).toBe(2);
});

test('tabs are deep-linkable and keyboard navigable', async ({ page }) => {
  await page.goto('http://127.0.0.1:9618/#library', { waitUntil: 'networkidle' });
  await expect(page.locator('#panel-library')).toBeVisible();
  await expect(page.locator('#tab-library')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#tab-library')).toHaveAttribute('tabindex', '0');
  await expect(page.locator('#tab-scout')).toHaveAttribute('tabindex', '-1');

  await page.locator('#tab-library').focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('#panel-ask')).toBeVisible();
  await expect(page.locator('#tab-ask')).toHaveAttribute('aria-selected', 'true');
  await expect(page).toHaveURL(/#ask$/);
});

test('ask tab shows previous questions and re-asks from history chips', async ({ page }) => {
  const qaRows = [{
    id: 1,
    question: '押金怎么收？',
    answer: '旧答案',
    place_id: null,
    created_at: Date.now() / 1000,
  }, {
    id: 2,
    question: '这家能现场修琴吗？',
    answer: '旧单店答案',
    place_id: 'place-1',
    place_name: "D'Class Guitar",
    created_at: Date.now() / 1000,
  }];
  await page.route('**/api/qa**', (route) => {
    const url = new URL(route.request().url());
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(url.searchParams.get('scope') === 'all' ? qaRows : [qaRows[0]]),
    });
  });
  const askBodies = [];
  await page.route('**/api/ask', async (route) => {
    askBodies.push(route.request().postDataJSON());
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        answer: '押金通常需要现场确认。',
        cached: true,
        matched: '押金怎么收？',
        created_at: Date.now() / 1000,
        model: 'test-model',
        provider: 'test-provider',
      }),
    });
  });

  await page.goto('http://127.0.0.1:9618/#ask', { waitUntil: 'networkidle' });

  await expect(page.locator('#ask-history')).toContainText('问过 asked');
  const chip = page.getByRole('button', { name: '押金怎么收？' });
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(page.locator('#ask-question')).toHaveValue('押金怎么收？');
  await expect(page.locator('#ask-answer')).toContainText('押金通常需要现场确认');

  const shopChip = page.getByRole('button', { name: /这家能现场修琴吗/ });
  await expect(shopChip).toContainText("D'Class Guitar");
  await shopChip.click();
  await expect(page.locator('#ask-question')).toHaveValue('这家能现场修琴吗？');
  expect(askBodies.at(-1)).toMatchObject({ question: '这家能现场修琴吗？', place_id: 'place-1' });
});

test('shop dossier focuses close control and restores opener focus', async ({ page }) => {
  await page.route('**/api/places/focus-test', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      place: {
        place_id: 'focus-test',
        name: 'Focus Test Cafe',
        category: 'Cafe',
        rating: 4.5,
        review_count: 12,
        cached_reviews: 12,
        last_refreshed: Date.now() / 1000,
      },
      reviews: [],
      report: null,
    }),
  }));
  await page.goto('http://127.0.0.1:9618', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    const btn = document.createElement('button');
    btn.id = 'focus-opener';
    btn.type = 'button';
    btn.textContent = 'Open focus test';
    document.body.appendChild(btn);
  });

  await page.locator('#focus-opener').focus();
  await page.evaluate(() => window.__pi.openDetail('focus-test'));
  await expect(page.locator('#detail-close')).toBeFocused();

  await page.keyboard.press('Shift+Tab');
  await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest('#detail-overlay')))).toBe(true);

  await page.locator('.detail-reviews summary').focus();
  await page.keyboard.press('Tab');
  await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest('#detail-overlay')))).toBe(true);

  await page.keyboard.press('Escape');
  await expect(page.locator('#focus-opener')).toBeFocused();
});
