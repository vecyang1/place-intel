import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: 'output/playwright/test-results',
  fullyParallel: false,
  webServer: {
    command: '.venv/bin/placeintel-web',
    url: 'http://127.0.0.1:9618/api/health',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [{
    name: 'chromium',
    use: {
      browserName: 'chromium',
      extraHTTPHeaders: { 'X-PlaceIntel-Test': 'playwright' },
    },
  }],
});
