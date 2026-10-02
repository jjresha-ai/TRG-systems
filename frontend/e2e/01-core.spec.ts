import { expect, test } from '@playwright/test'
import { login } from './helpers'

test.beforeEach(async ({ page }) => { await login(page) })

test('contacts list shows the seeded book and opens a detail page', async ({ page }) => {
  await page.getByRole('link', { name: 'Contacts' }).click()
  await expect(page.getByText(/\d{3} people across owners/)).toBeVisible()
  expect(await page.locator('tbody tr').count()).toBe(25)
  await page.getByLabel('Type').selectOption('investor')
  await expect(page.locator('tbody tr').first()).toBeVisible()
  await page.locator('tbody tr').first().click()
  await expect(page.getByText('Entities & roles')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'What they own' })).toBeVisible()
})

test('property screen: filter by loan maturity and see owner graph', async ({ page }) => {
  await page.getByRole('link', { name: 'Properties' }).click()
  await page.getByLabel('Loan maturity').selectOption('12')
  await expect(page.locator('tbody tr').first()).toBeVisible()
  await page.locator('tbody tr').first().click()
  await expect(page.getByRole('heading', { name: 'Who owns this' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Ownership history' })).toBeVisible()
  await expect(page.getByText('Debt', { exact: true })).toBeVisible()
})

test('company detail lists principals and holdings, linking back to people', async ({ page }) => {
  await page.getByRole('link', { name: 'Companies' }).click()
  await page.getByLabel('Kind').selectOption('llc')
  await page.locator('tbody tr').first().click()
  await expect(page.getByText('People behind the entity')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Current holdings' })).toBeVisible()
})

test('global search is graph-aware: property address shows its owner', async ({ page }) => {
  await page.getByRole('link', { name: 'Properties' }).click()
  const addr = (await page.locator('tbody tr').first().locator('td').first().locator('div').nth(1).innerText()).split(',')[0]
  await page.getByLabel('Global search').fill(addr)
  const opt = page.getByRole('option').first()
  await expect(opt).toBeVisible()
  await expect(opt).toContainText('↔')
  await opt.click()
  await expect(page.getByRole('heading', { name: 'Who owns this' })).toBeVisible()
})

test('creating a duplicate contact is blocked by the backend', async ({ page }) => {
  await page.getByRole('link', { name: 'Contacts' }).click()
  await page.locator('tbody tr').first().click()
  const email = await page.locator('a[href^="mailto:"]').first().innerText()
  await page.getByRole('link', { name: 'Contacts' }).click()
  await page.getByRole('button', { name: 'New contact' }).click()
  await page.getByLabel('First name').fill('Dupe')
  await page.getByLabel('Last name').fill('Tester')
  await page.getByLabel('Email').fill(email.toUpperCase())
  await page.getByRole('button', { name: 'Create contact' }).click()
  await expect(page.getByRole('alert')).toContainText('Duplicate contact')
})

test('data quality queue shows possible duplicates and merges then undoes', async ({ page }) => {
  await page.getByRole('link', { name: 'Data Quality' }).click()
  await expect(page.getByText('similar name').first()).toBeVisible()
  const before = await page.getByRole('button', { name: 'Keep first' }).count()
  await page.getByRole('button', { name: 'Keep first' }).first().click()
  await expect(page.getByText(/^Merged /)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Keep first' })).toHaveCount(before - 1)
  await page.getByRole('button', { name: 'Undo' }).first().click()
  await expect(page.getByText('Merge undone.')).toBeVisible()
})
