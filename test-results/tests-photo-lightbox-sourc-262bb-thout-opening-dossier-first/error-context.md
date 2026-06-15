# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests/photo-lightbox-source-url.spec.js >> library card photo opens the full place gallery without opening dossier first
- Location: tests/photo-lightbox-source-url.spec.js:68:1

# Error details

```
Error: expect(locator).toHaveText(expected) failed

Locator:  locator('#photo-lightbox-count')
Expected: "1/8"
Received: "1/1"
Timeout:  5000ms

Call log:
  - Expect "toHaveText" with timeout 5000ms
  - waiting for locator('#photo-lightbox-count')
    14 × locator resolved to <span aria-live="polite" id="photo-lightbox-count" class="photo-lightbox-count">1/1</span>
       - unexpected value "1/1"

```

```yaml
- text: 1/1
```

# Test source

```ts
  12  |     rating: 5,
  13  |     date: `2026-06-${String(i + 1).padStart(2, '0')}`,
  14  |   }));
  15  |   const place = {
  16  |     place_id: 'many-photos',
  17  |     name: 'Many Photos Cafe',
  18  |     category: 'Cafe',
  19  |     rating: 4.8,
  20  |     review_count: 88,
  21  |     cached_reviews: 88,
  22  |     address: 'Hoi An',
  23  |     last_refreshed: now,
  24  |     thumbnail: photos[0],
  25  |   };
  26  | 
  27  |   await page.route('**/api/places', (route) => route.fulfill({
  28  |     contentType: 'application/json',
  29  |     body: JSON.stringify([place]),
  30  |   }));
  31  |   await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));
  32  |   await page.route('**/api/places/many-photos', (route) => route.fulfill({
  33  |     contentType: 'application/json',
  34  |     body: JSON.stringify({
  35  |       place,
  36  |       photos,
  37  |       reviews: [],
  38  |       report: { profile: 'generic', created_at: now, md: '# Report', json: { verdict: 'Use photos to verify storefront.' } },
  39  |     }),
  40  |   }));
  41  | 
  42  |   await page.goto('http://127.0.0.1:9618/#library', { waitUntil: 'networkidle' });
  43  |   await page.locator('[data-open-place="many-photos"]').click();
  44  | 
  45  |   const stripButtons = page.locator('#detail-body .photo-strip .source-photo');
  46  |   await expect(stripButtons).toHaveCount(8);
  47  |   await stripButtons.first().click();
  48  | 
  49  |   await expect(page.locator('#photo-lightbox')).toBeVisible();
  50  |   await expect(page.locator('#photo-lightbox-count')).toHaveText('1/8');
  51  |   const source = page.locator('#photo-lightbox-source');
  52  |   await expect(source).toHaveText('https://images.example/source-1.jpg');
  53  |   await expect(source).toHaveAttribute('href', 'https://images.example/source-1.jpg');
  54  | 
  55  |   for (let i = 0; i < 7; i += 1) {
  56  |     await page.locator('#photo-lightbox-next').click();
  57  |   }
  58  |   await expect(page.locator('#photo-lightbox-count')).toHaveText('8/8');
  59  |   await expect(page.locator('#photo-lightbox-img')).toHaveAttribute('src', 'https://images.example/source-8.jpg');
  60  |   await expect(source).toHaveText('https://images.example/source-8.jpg');
  61  |   if (process.env.PLACEINTEL_SCREENSHOT_PROOF) {
  62  |     await page.screenshot({ path: 'output/playwright/placeintel-v0439-source-url-gallery.png', fullPage: false });
  63  |   }
  64  |   await page.keyboard.press('ArrowLeft');
  65  |   await expect(page.locator('#photo-lightbox-count')).toHaveText('7/8');
  66  | });
  67  | 
  68  | test('library card photo opens the full place gallery without opening dossier first', async ({ page }) => {
  69  |   const now = Date.now() / 1000;
  70  |   const photos = Array.from({ length: 8 }, (_, i) => ({
  71  |     url: `https://images.example/card-source-${i + 1}.jpg`,
  72  |     thumb_url: `https://images.example/card-source-${i + 1}-thumb.jpg`,
  73  |     source: 'scraper-pro',
  74  |     kind: 'review',
  75  |     review_id: `card-r${i + 1}`,
  76  |     author: `Card Author ${i + 1}`,
  77  |     rating: 5,
  78  |     date: `2026-06-${String(i + 1).padStart(2, '0')}`,
  79  |   }));
  80  |   const place = {
  81  |     place_id: 'card-many-photos',
  82  |     name: 'Card Many Photos Cafe',
  83  |     category: 'Cafe',
  84  |     rating: 4.8,
  85  |     review_count: 88,
  86  |     cached_reviews: 88,
  87  |     address: 'Hoi An',
  88  |     last_refreshed: now,
  89  |     thumbnail: photos[0],
  90  |   };
  91  | 
  92  |   await page.route('**/api/places', (route) => route.fulfill({
  93  |     contentType: 'application/json',
  94  |     body: JSON.stringify([place]),
  95  |   }));
  96  |   await page.route('**/api/searches', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }));
  97  |   await page.route('**/api/places/card-many-photos', (route) => route.fulfill({
  98  |     contentType: 'application/json',
  99  |     body: JSON.stringify({
  100 |       place,
  101 |       photos,
  102 |       reviews: [],
  103 |       report: null,
  104 |     }),
  105 |   }));
  106 | 
  107 |   await page.goto('http://127.0.0.1:9618/#library', { waitUntil: 'networkidle' });
  108 |   await page.locator('#library-grid .shop-card').filter({ hasText: 'Card Many Photos Cafe' }).locator('.source-photo').click();
  109 | 
  110 |   await expect(page.locator('#detail-overlay')).toBeHidden();
  111 |   await expect(page.locator('#photo-lightbox')).toBeVisible();
> 112 |   await expect(page.locator('#photo-lightbox-count')).toHaveText('1/8');
      |                                                       ^ Error: expect(locator).toHaveText(expected) failed
  113 |   await expect(page.locator('#photo-lightbox-source')).toHaveText('https://images.example/card-source-1.jpg');
  114 | 
  115 |   await page.locator('#photo-lightbox-next').click();
  116 |   await expect(page.locator('#photo-lightbox-count')).toHaveText('2/8');
  117 |   await expect(page.locator('#photo-lightbox-img')).toHaveAttribute('src', 'https://images.example/card-source-2.jpg');
  118 | });
  119 | 
```