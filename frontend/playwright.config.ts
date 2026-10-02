import { defineConfig } from '@playwright/test'

// ADR 0031: e2e runs against an isolated real stack (own FastAPI + own freshly seeded SQLite DB + own Vite),
// so tests never touch the demo database that is on screen.
const API = 8100
const WEB = 5273
const DB = '/tmp/trg-e2e.db'
const backendEnv = `TRG_DATABASE_URL=sqlite:///${DB} TRG_SCHEDULER=0`

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${WEB}`,
    headless: true,
    launchOptions: { executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox'] },
  },
  webServer: [
    {
      command: `rm -f ${DB}* && ${backendEnv} python -m app.seed && ${backendEnv} python -m uvicorn app.main:app --port ${API}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${API}/api/health`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `API_TARGET=http://127.0.0.1:${API} npx vite --port ${WEB} --strictPort`,
      url: `http://localhost:${WEB}`,
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
})
