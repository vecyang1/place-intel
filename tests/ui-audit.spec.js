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
