import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { login } from './helpers'

const tag = () => Math.random().toString(36).slice(2, 8)

async function preview(page: Page, entityLabel: string, csv: string, source: string, mode = 'Update it, create the rest') {
  await page.getByRole('link', { name: 'Import / Export' }).click()
  await page.getByRole('button', { name: new RegExp(entityLabel) }).click()
  await page.getByLabel('Source name').fill(source)
  await page.getByLabel('Import mode').selectOption({ label: mode })
  await page.getByLabel('Import file').setInputFiles({ name: 'upload.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) })
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByTestId('counts')).toBeVisible()
}

test('owner portfolio import: preview, commit, then the owner graph is searchable', async ({ page }) => {
  const t = tag()
  await login(page)
  const csv = [
    'Owner First,Owner Last,Owner Email,Entity,Property Address,City,Property Type,SF,Acquired',
    `Ira,Importer${t},ira${t}@e2e.test,Lagoon ${t} Holdings LLC,${t.slice(0, 3)}1 Lagoon Way,Irvine,Retail,9000,3/1/2014`,
    `Ira,Importer${t},ira${t}@e2e.test,Lagoon ${t} Holdings LLC,${t.slice(0, 3)}2 Lagoon Way,Tustin,Industrial,32000,2019-05-20`,
    `Bad,Row${t},bad${t}@e2e.test,Bad ${t} LLC,${t.slice(0, 3)}3 Lagoon Way,Irvine,Hotel,1000,`,
  ].join('\n')
  await preview(page, 'Owners \\+ entities', csv, `E2E feed ${t}`)
  await expect(page.getByTestId('counts').getByText('Will create').locator('xpath=following-sibling::div[1]')).toHaveText('2')
  await expect(page.getByTestId('counts').getByText('Errors').locator('xpath=following-sibling::div[1]')).toHaveText('1')
  await page.getByRole('tab', { name: 'error' }).click()
  await expect(page.getByTestId('rows')).toContainText('retail or industrial')
  await page.getByRole('button', { name: /Import 2 rows/ }).click()
  await expect(page.getByRole('status')).toContainText('Import complete: 1 contacts, 1 companies, 2 properties', { timeout: 20_000 })
  await page.getByLabel('Global search').fill(`Importer${t}`)
  const opt = page.getByRole('option').first()
  await expect(opt).toContainText('↔')
  await expect(opt).toContainText('1 Lagoon Way')
})

test('mapping can be corrected and the preview recomputes', async ({ page }) => {
  const t = tag()
  await login(page)
  await preview(page, 'Contacts', `Surname,Given,Mail\nZed${t},Zoe,zoe${t}@e2e.test`, `E2E map ${t}`)
  await expect(page.getByTestId('counts')).toContainText('Errors')
  await page.getByLabel('Map Last name').selectOption('Surname')
  await page.getByLabel('Map First name').selectOption('Given')
  await page.getByLabel('Map Email').selectOption('Mail')
  await page.getByRole('button', { name: 'Re-run preview with this mapping' }).click()
  await expect(page.getByTestId('counts').getByText('Will create').locator('xpath=following-sibling::div[1]')).toHaveText('1')
})

test('duplicates are flagged in the preview and never created', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Contacts' }).click()
  await page.locator('tbody tr').first().click()
  const email = await page.locator('a[href^="mailto:"]').first().innerText()
  await preview(page, 'Contacts', `first_name,last_name,email\nSomeone,Else,${email.toUpperCase()}`, 'E2E dup check', 'Skip it (create new only)')
  await expect(page.getByTestId('counts').getByText('Duplicates').locator('xpath=following-sibling::div[1]')).toHaveText('1')
  await expect(page.getByRole('button', { name: /Import 0 rows/ })).toBeDisabled()
})

test('rollback removes an unmodified import and the history shows it', async ({ page }) => {
  const t = tag()
  await login(page)
  await preview(page, 'Companies', `name,kind\nRollback ${t} Capital LLC,llc`, `E2E rollback ${t}`)
  await page.getByRole('button', { name: /Import 1 rows/ }).click()
  await expect(page.getByRole('status')).toContainText('1 companies', { timeout: 20_000 })
  await page.waitForTimeout(2500)
  await page.getByRole('button', { name: 'Roll back this import' }).click()
  await expect(page.getByText(/Rolled back: removed 0 contacts, 1 companies/)).toBeVisible()
  await page.getByRole('button', { name: 'Close' }).click()
  await page.getByRole('tab', { name: 'History' }).click()
  await expect(page.getByTestId('history').getByText(`E2E rollback ${t}`)).toBeVisible()
  await expect(page.getByTestId('history').getByText('rolled back').first()).toBeVisible()
})

test('seeded import history shows real files and the CoStar import', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Import / Export' }).click()
  await page.getByRole('tab', { name: 'History' }).click()
  await expect(page.getByTestId('history').getByText('costar-orange-county-retail-industrial.csv')).toBeVisible()
  await page.getByTestId('history').getByText('costar-orange-county-retail-industrial.csv').click()
  await expect(page.getByTestId('rows')).toBeVisible()
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Row error report' }).click()])
  const text = readFileSync((await dl.path())!, 'utf8')
  expect(text).toContain('Property type must be retail or industrial')
})

test('export a saved view to CSV and the full workbook; assistants have no export', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Import / Export' }).click()
  await page.getByRole('tab', { name: 'Export' }).click()
  await page.getByLabel('Export view').selectOption({ index: 1 })
  const [csv] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download', exact: true }).click()])
  expect(csv.suggestedFilename()).toBe('property.csv')
  expect(readFileSync((await csv.path())!, 'utf8').split(/\r?\n/)[0]).toContain('Address')
  await expect(page.getByRole('status')).toContainText('audit trail')
  const [full] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download full export' }).click()])
  expect(full.suggestedFilename()).toBe('trg-full-export.xlsx')
  expect(readFileSync((await full.path())!).subarray(0, 2).toString()).toBe('PK')
  await page.getByLabel('Sign out').click()
  await login(page, 'priya@resha.group')
  await page.getByRole('link', { name: 'Import / Export' }).click()
  await page.getByRole('tab', { name: 'Export' }).click()
  await expect(page.getByText('Your role does not have export access.')).toBeVisible()
})
