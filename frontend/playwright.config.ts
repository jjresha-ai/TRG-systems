import { defineConfig } from '@playwright/test'

// Tests run against the already-running dev servers (Vite :5173 -> FastAPI :8000) with the seeded demo DB (ADR 0030).
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    headless: true,
    launchOptions: { executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox'] },
  },
})
