import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.MINIAPP_E2E_BASE_URL ?? 'http://127.0.0.1:8080/mini-app/'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 7_500 },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [['line'], ['html', { outputFolder: 'playwright-report', open: 'never' }]]
    : 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  outputDir: 'test-results',
  projects: [
    {
      name: 'telegram-android-chromium',
      use: { ...devices['Pixel 7'] },
    },
    {
      name: 'telegram-ios-webkit',
      use: { ...devices['iPhone 14'] },
    },
  ],
})
