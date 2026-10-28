import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const viteEntry = fileURLToPath(new URL('./node_modules/vite/bin/vite.js', import.meta.url))

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    browserName: 'chromium',
    launchOptions: process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : undefined,
    headless: true,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `"${process.execPath}" "${viteEntry}" --host 127.0.0.1 --port 4173 --strictPort`,
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
})
