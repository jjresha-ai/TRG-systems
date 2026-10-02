import { expect, test } from '@playwright/test'
import { login } from './helpers'

test('prospecting board shows scored leads and explains the score', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Prospecting' }).click()
  await expect(page.getByTestId('col-new').locator('button').first()).toBeVisible()
  await page.getByTestId('col-new').locator('button').first().click()
  await expect(page.getByText('Why this score')).toBeVisible()
  await expect(page.getByText('Triggered by')).toBeVisible()
})

test('a lead can be converted to a contact, creating real records', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Prospecting' }).click()
  const col = page.getByTestId('col-qualified')
  const before = await page.getByTestId('col-converted').getByText(/^\d+$/).first().innerText()
  await col.locator('button').first().click()
  await page.getByRole('button', { name: 'Convert to contact' }).click()
  await expect(page.getByText('Why this score')).toBeHidden()
  await expect(page.getByTestId('col-converted').getByText(/^\d+$/).first()).not.toHaveText(before)
})

test('trigger rules tab: admin runs the hold/sell job, second run is a no-op', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Prospecting' }).click()
  await page.getByRole('tab', { name: 'Triggers & rules' }).click()
  await page.getByRole('button', { name: 'Run triggers now' }).click()
  await expect(page.getByText(/Created 0 leads/)).toBeVisible()
  await expect(page.getByText('Long hold: 15+ years')).toBeVisible()
})

test('listings: status filter, detail with buyer funnel, advancing a buyer', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Listings', exact: true }).click()
  await page.getByRole('tab', { name: 'Active' }).click()
  await expect(page.locator('tbody tr').first()).toBeVisible()
  for (const badge of await page.locator('tbody tr td:nth-child(2)').allInnerTexts()) expect(badge.toLowerCase()).toContain('active')
  await page.locator('tbody tr').first().click()
  await expect(page.getByLabel('Buyer funnel')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Broker team' })).toBeVisible()
  const sel = page.getByRole('combobox', { name: /^Move / }).first()
  await sel.selectOption({ label: 'Declined' })
  await expect(page.getByText('Declined').first()).toBeVisible()
})

test('new listing flow enforces one active sale listing per property', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Listings', exact: true }).click()
  await page.getByRole('tab', { name: 'Active' }).click()
  const addr = (await page.locator('tbody tr').first().locator('td').first().locator('div').nth(1).innerText()).split(',')[0].trim()
  const street = (await page.locator('tbody tr').first().locator('td').first().locator('div').first().innerText()).trim()
  await page.getByRole('button', { name: 'New listing' }).click()
  await page.getByPlaceholder('Address, city or APN…').fill(street.match(/^\d+ .+/) ? street : addr)
  await page.getByRole('dialog').locator('li button').first().click()
  await page.getByRole('button', { name: 'Create listing' }).click()
  await expect(page.getByRole('button', { name: 'Mark active' })).toBeVisible()
  await page.getByRole('button', { name: 'Mark active' }).click()
  await page.getByLabel('List price').fill('5000000')
  await page.getByLabel('Expiration date').fill('2027-06-30')
  await page.getByRole('button', { name: 'Activate' }).click()
  await expect(page.getByRole('alert')).toContainText('already has an active sale listing')
})

test('commission is restricted for read-only users', async ({ page }) => {
  await login(page, 'auditor@resha.group')
  await page.getByRole('link', { name: 'Listings', exact: true }).click()
  await page.locator('tbody tr').first().click()
  await expect(page.getByText('Restricted')).toBeVisible()
  await expect(page.getByText('Expected commission')).toHaveCount(0)
})
