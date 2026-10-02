import { chromium } from '@playwright/test'
const [,, path, out] = process.argv
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox'] })
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://localhost:5173/login')
await p.getByLabel('Email').fill('jim@resha.group'); await p.getByLabel('Password').fill('demo1234'); await p.getByRole('button', { name: 'Sign in' }).click()
await p.waitForSelector('text=Live build')
await p.goto('http://localhost:5173' + path); await p.waitForTimeout(1500)
await p.screenshot({ path: out })
await b.close()
