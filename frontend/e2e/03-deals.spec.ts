import { expect, test } from '@playwright/test'
import { login } from './helpers'

// wide viewport so every kanban column is on screen: HTML5 drag-and-drop between off-screen columns is not a realistic user action
test.use({ viewport: { width: 2600, height: 1100 } })

test('board shows the seller pipeline with stage totals and forecast', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Deals' }).click()
  for (const s of ['prospect', 'marketing', 'under_contract', 'closed']) await expect(page.getByTestId(`stage-${s}`)).toBeVisible()
  await expect(page.getByText('Weighted commission').first()).toBeVisible()
  await expect(page.getByText(/Forecast by expected close month/)).toBeVisible()
  expect(await page.getByTestId('deal-card').count()).toBeGreaterThan(10)
})

test('drag a deal to the next stage and the backend records it', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Deals' }).click()
  await page.waitForLoadState('networkidle')
  await expect(page.locator('.recharts-surface').first()).toBeVisible()
  const from = page.getByTestId('stage-marketing')
  const to = page.getByTestId('stage-offers')
  const countBefore = Number((await to.locator('h3').locator('xpath=following-sibling::span').innerText()).trim())
  const href = await from.getByTestId('deal-card').first().getAttribute('href')
  const card = from.locator(`a[href="${href}"]`)
  await card.scrollIntoViewIfNeeded()
  await card.dragTo(to)
  await expect(to.locator(`a[href="${href}"]`)).toBeVisible()
  await expect(to.locator('h3').locator('xpath=following-sibling::span')).toHaveText(String(countBefore + 1))
  await to.locator(`a[href="${href}"]`).click()
  await expect(page.getByRole('heading', { name: 'Stage history' })).toBeVisible()
  await expect(page.getByText('from Marketing').first()).toBeVisible()
})

test('dragging to Lost asks for a reason (backend rule) and records it', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Deals' }).click()
  await page.getByTestId('stage-prospect').getByTestId('deal-card').first().click()
  await page.getByRole('button', { name: 'Lost', exact: true }).click()
  await page.getByLabel('Lost reason').fill('Owner decided to hold')
  await page.getByRole('button', { name: 'Move deal' }).click()
  await expect(page.getByText('Lost: Owner decided to hold')).toBeVisible()
})

test('a capital deal can be closed from the stage stepper and history records it', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Deals' }).click()
  await page.getByRole('tab', { name: 'Capital' }).click()
  await page.getByTestId('stage-committed').getByTestId('deal-card').first().click()
  await page.getByRole('button', { name: 'Closed', exact: true }).click()
  await expect(page.getByText('Stage history')).toBeVisible()
  await expect(page.locator('li', { hasText: 'Closed' }).first()).toBeVisible()
})

test('commission splits over 100% are rejected', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Deals' }).click()
  await page.getByTestId('stage-under_contract').getByTestId('deal-card').first().click()
  await expect(page.getByRole('heading', { name: 'Commission splits' })).toBeVisible()
  await page.getByRole('heading', { name: 'Commission splits' }).locator('xpath=../..').getByRole('button', { name: 'Edit' }).click()
  const rows = page.getByRole('dialog')
  await rows.getByLabel('Recipient 1').selectOption({ index: 1 })
  await rows.getByLabel('Percent 1').fill('80')
  await rows.getByLabel('Recipient 2').selectOption({ index: 2 })
  await rows.getByLabel('Percent 2').fill('40')
  await rows.getByRole('button', { name: 'Save splits' }).click()
  await expect(rows.getByRole('alert')).toContainText('exceed 100')
})

test('read-only role sees volume but not commission', async ({ page }) => {
  await login(page, 'auditor@resha.group')
  await page.getByRole('link', { name: 'Deals' }).click()
  await expect(page.getByText('Restricted').first()).toBeVisible()
  await expect(page.getByText('Weighted commission')).toHaveCount(0)
  await page.getByTestId('deal-card').first().click()
  await expect(page.getByRole('heading', { name: 'Commission splits' })).toHaveCount(0)
})
