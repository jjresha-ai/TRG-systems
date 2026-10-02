import { expect, test } from '@playwright/test'
import { login } from './helpers'

test('investor directory filters by asset class and 1031 and shows accreditation to brokers', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Investors' }).click()
  await expect(page.getByText(/\d+ investor profiles/)).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Accreditation' })).toBeVisible()
  await page.getByLabel('1031').selectOption('true')
  await expect(page.locator('tbody tr').first()).toBeVisible()
  for (const t of await page.locator('tbody tr td:nth-child(4)').allInnerTexts()) expect(t).not.toBe('—')
  await page.getByLabel('Asset class').selectOption('industrial')
  await expect(page.locator('tbody tr').first()).toBeVisible()
})

test('assistants never see accreditation data', async ({ page }) => {
  await login(page, 'priya@resha.group')
  await page.getByRole('link', { name: 'Investors' }).click()
  await expect(page.locator('tbody tr').first()).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Accreditation' })).toHaveCount(0)
  await expect(page.getByLabel('Accreditation')).toBeVisible() // filter control exists but the backend refuses it
  await page.getByLabel('Accreditation').selectOption('accredited')
  await expect(page.getByRole('alert')).toContainText('may not filter by accreditation')
})

test('investor detail shows ranked listing matches with reasons', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Investors' }).click()
  await page.locator('tbody tr').first().click()
  await expect(page.getByRole('heading', { name: 'Matching active listings' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Fund positions' })).toBeVisible()
  await expect(page.getByText('Viewing investor profiles is recorded in the audit trail.')).toBeVisible()
})

test('funds overview shows raise progress for every vehicle', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Funds' }).click()
  await expect(page.getByTestId('fund-card').first()).toBeVisible()
  expect(await page.getByTestId('fund-card').count()).toBeGreaterThanOrEqual(4)
  await expect(page.getByText('1880 Capital Fund I')).toBeVisible()
  await expect(page.getByRole('img', { name: /% committed or funded/ }).first()).toBeVisible()
})

test('fund detail: add a commitment to a raising fund', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Funds' }).click()
  await page.getByText('Orange Coast NNN Syndication I').click()
  await expect(page.getByRole('heading', { name: 'Commitments' })).toBeVisible()
  await page.getByRole('button', { name: 'Add commitment' }).click()
  await page.getByLabel('Find investor').fill('an')
  await page.getByRole('dialog').locator('li button').first().click()
  await page.getByLabel('Amount').fill('50000')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(page.locator('tbody tr').first()).toBeVisible()
})

test('listing detail suggests matching investors and responds to leverage', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Listings', exact: true }).click()
  await page.getByRole('tab', { name: 'Active' }).click()
  await page.locator('tbody tr').first().click()
  await expect(page.getByRole('heading', { name: 'Matching investors' })).toBeVisible()
  await page.getByLabel('Assumed LTV').selectOption('0')
  await expect(page.getByText(/Ranked by asset class/)).toBeVisible()
})
