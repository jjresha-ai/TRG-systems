import { expect, test } from '@playwright/test'
import { login } from './helpers'

test('dashboard shows KPIs, goals, charts and attention items from live data', async ({ page }) => {
  await login(page)
  await expect(page.getByText('YTD closed volume')).toBeVisible()
  await expect(page.getByText('YTD GCI')).toBeVisible()
  expect(await page.getByTestId('goal').count()).toBe(4)
  await expect(page.locator('.recharts-surface').first()).toBeVisible()
  await expect(page.getByText('Hottest new leads')).toBeVisible()
  await expect(page.getByText('Needs attention')).toBeVisible()
})

test('dashboard for a read-only role hides commission', async ({ page }) => {
  await login(page, 'auditor@resha.group')
  await expect(page.getByText('Restricted').first()).toBeVisible()
  await expect(page.getByText('YTD GCI')).toBeVisible()
  await expect(page.getByText('Weighted volume', { exact: true })).toBeVisible()
})

test('production report: group by month, totals and goal progress', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Reports' }).click()
  await expect(page.getByTestId('report-table')).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'gci' })).toBeVisible()
  await expect(page.getByTestId('report-totals')).toContainText('closed volume')
  await expect(page.getByText('Goal progress')).toBeVisible()
  await page.getByLabel('Group by').selectOption('month')
  await expect(page.locator('tbody tr').first().locator('td').first()).toContainText(/^\d{4}-\d{2}$/)
})

test('every report in the catalog renders rows', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Reports' }).click()
  for (const name of ['Pipeline & forecast', 'Listings', 'Buyer interest', 'Prospecting', 'Owner recency', 'Time in stage', 'Investor capital']) {
    await page.getByRole('navigation', { name: 'Report catalog' }).getByText(name, { exact: true }).click()
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
    await expect(page.locator('tbody tr').first()).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  }
})

test('CSV export downloads a real file with a header row', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Reports' }).click()
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'CSV' }).click()])
  expect(download.suggestedFilename()).toBe('production.csv')
  const { createReadStream } = await import('node:fs')
  const chunks: Buffer[] = []
  for await (const c of createReadStream((await download.path())!)) chunks.push(c as Buffer)
  const text = Buffer.concat(chunks).toString()
  expect(text.trim().split(/\r?\n/)[0]).toBe('group,listings_taken,closed_deals,closed_volume,gci')
  expect(text.trim().split(/\r?\n/).length).toBeGreaterThan(2)
})

test('assistants cannot export and do not see commission columns', async ({ page }) => {
  await login(page, 'priya@resha.group')
  await page.getByRole('link', { name: 'Reports' }).click()
  await expect(page.getByTestId('report-table')).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'gci' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'CSV' })).toHaveCount(0)
})
