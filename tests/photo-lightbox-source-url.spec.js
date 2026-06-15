import { test, expect } from '@playwright/test';

test('photo lightbox quotes source URL and can browse more URL-only images', async ({ page }) => {
  const now = Date.now() / 1000;
  const photos = Array.from({ length: 8 }, (_, i) => ({
    url: `https://images.example/source-${i + 1}.jpg`,
    thumb_url: `https://images.example/source-${i + 1}-thumb.jpg`,
    source: 'scraper-pro',
    kind: 'review',
    review_id: `r${i + 1}`,
    author: `Author ${i + 1}`,
    rating: 5,
    date: `2026-06-${String(i + 1).padStart(2, '0')}`,
  }));
  const place = {
    place_id: 'many-photos',
    name: 'Many Photos Cafe',
    category: 'Cafe',
    rating: 4.8,
    review_count: 88,
    cached_reviews: 88,
    address: 'Hoi An',
    last_refreshed: now,
    thumbnail: photos[0],
  };

  await page.route('**/api/places', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([place]),
  }));
  await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/places/many-photos', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      place,
      photos,
      reviews: [],
      report: { profile: 'generic', created_at: now, md: '# Report', json: { verdict: 'Use photos to verify storefront.' } },
    }),
  }));

  await page.goto('http://127.0.0.1:9618/#library', { waitUntil: 'networkidle' });
  await page.locator('[data-open-place="many-photos"]').click();

  const stripButtons = page.locator('#detail-body .photo-strip .source-photo');
  await expect(stripButtons).toHaveCount(8);
  await stripButtons.first().click();

  await expect(page.locator('#photo-lightbox')).toBeVisible();
  await expect(page.locator('#photo-lightbox-count')).toHaveText('1/8');
  const source = page.locator('#photo-lightbox-source');
  await expect(source).toHaveText('https://images.example/source-1.jpg');
  await expect(source).toHaveAttribute('href', 'https://images.example/source-1.jpg');

  for (let i = 0; i < 7; i += 1) {
    await page.locator('#photo-lightbox-next').click();
  }
  await expect(page.locator('#photo-lightbox-count')).toHaveText('8/8');
  await expect(page.locator('#photo-lightbox-img')).toHaveAttribute('src', 'https://images.example/source-8.jpg');
  await expect(source).toHaveText('https://images.example/source-8.jpg');
  if (process.env.PLACEINTEL_SCREENSHOT_PROOF) {
    await page.screenshot({ path: 'output/playwright/placeintel-v0439-source-url-gallery.png', fullPage: false });
  }
  await page.keyboard.press('ArrowLeft');
  await expect(page.locator('#photo-lightbox-count')).toHaveText('7/8');
});

test('library card photo opens the full place gallery without opening dossier first', async ({ page }) => {
  const now = Date.now() / 1000;
  const photos = Array.from({ length: 8 }, (_, i) => ({
    url: `https://images.example/card-source-${i + 1}.jpg`,
    thumb_url: `https://images.example/card-source-${i + 1}-thumb.jpg`,
    source: 'scraper-pro',
    kind: 'review',
    review_id: `card-r${i + 1}`,
    author: `Card Author ${i + 1}`,
    rating: 5,
    date: `2026-06-${String(i + 1).padStart(2, '0')}`,
  }));
  const place = {
    place_id: 'card-many-photos',
    name: 'Card Many Photos Cafe',
    category: 'Cafe',
    rating: 4.8,
    review_count: 88,
    cached_reviews: 88,
    address: 'Hoi An',
    last_refreshed: now,
    thumbnail: photos[0],
  };

  await page.route('**/api/places', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([place]),
  }));
  await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/places/card-many-photos', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      place,
      photos,
      reviews: [],
      report: null,
    }),
  }));

  await page.goto('http://127.0.0.1:9618/#library', { waitUntil: 'networkidle' });
  await page.locator('#library-grid .shop-card').filter({ hasText: 'Card Many Photos Cafe' }).locator('.source-photo').click();

  await expect(page.locator('#detail-overlay')).toBeHidden();
  await expect(page.locator('#photo-lightbox')).toBeVisible();
  await expect(page.locator('#photo-lightbox-count')).toHaveText('1/8');
  await expect(page.locator('#photo-lightbox-source')).toHaveText('https://images.example/card-source-1.jpg');

  await page.locator('#photo-lightbox-next').click();
  await expect(page.locator('#photo-lightbox-count')).toHaveText('2/8');
  await expect(page.locator('#photo-lightbox-img')).toHaveAttribute('src', 'https://images.example/card-source-2.jpg');
});
