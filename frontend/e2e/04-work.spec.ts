import { expect, test } from '@playwright/test'
import { login } from './helpers'

test('agenda shows overdue, today and this week with counts', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Tasks & Activity' }).click()
  for (const k of ['overdue', 'today', 'this-week']) await expect(page.getByTestId(`agenda-${k}`)).toBeVisible()
  expect(await page.getByTestId('task-row').count()).toBeGreaterThan(3)
})

test('completing a call task asks for the outcome and removes it from the agenda', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Tasks & Activity' }).click()
  const today = page.getByTestId('agenda-today')
  await expect(today.getByTestId('task-row').first()).toBeVisible()
  const before = await today.getByTestId('task-row').count()
  const row = today.getByTestId('task-row').filter({ has: page.getByRole('button', { name: /^Complete (Call|Follow-up call)/ }) }).first()
  await row.getByRole('button', { name: /^Complete / }).click()
  await page.getByLabel('Outcome').selectOption('spoke')
  await page.getByRole('button', { name: 'Mark complete' }).click()
  await expect(today.getByTestId('task-row')).toHaveCount(before - 1)
})

test('activity log lists logged activity and filters by type', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Tasks & Activity' }).click()
  await page.getByRole('tab', { name: 'Activity log' }).click()
  await expect(page.getByTestId('activity-row').first()).toBeVisible()
  await page.getByLabel('Type').selectOption('meeting')
  await expect(page.getByTestId('activity-row').first()).toBeVisible()
  await expect(page.getByText(/of \d+/).first()).toBeVisible()
})

test('contact timeline: log a call, add a note, upload a document with versioning', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Contacts' }).click()
  await page.getByLabel('Type').selectOption('owner')
  await page.locator('tbody tr').first().click()
  await expect(page.getByRole('heading', { name: 'Activity' })).toBeVisible()
  // log a call
  await page.getByRole('button', { name: 'Log / task' }).click()
  await page.getByLabel('Subject').fill('E2E logged call')
  await page.getByLabel('Call outcome').selectOption('spoke')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('E2E logged call')).toBeVisible()
  // note
  await page.getByRole('button', { name: 'Note', exact: true }).click()
  await page.getByLabel('Note', { exact: true }).fill('E2E note: owner wants a BOV in Q1')
  await page.getByRole('button', { name: 'Save note' }).click()
  await expect(page.getByText('E2E note: owner wants a BOV in Q1')).toBeVisible()
  // document, twice -> v2
  for (const body of ['one', 'two']) {
    await page.getByRole('button', { name: 'Document' }).click()
    await page.getByLabel('File').setInputFiles({ name: 'E2E OM.pdf', mimeType: 'application/pdf', buffer: Buffer.from(`%PDF-1.4\n% ${body}\n%%EOF`) })
    await page.getByLabel('Document type').selectOption('om')
    await page.getByRole('button', { name: 'Upload' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
  }
  await page.getByRole('tab', { name: /Documents/ }).click()
  await expect(page.getByTestId('doc-row').filter({ hasText: 'E2E OM.pdf' })).toHaveCount(1)
  await expect(page.getByText('v2 of 2')).toBeVisible()
})

test('uploading a disallowed file type is rejected by the backend', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Properties' }).click()
  await page.locator('tbody tr').first().click()
  await page.getByRole('button', { name: 'Document' }).click()
  await page.getByLabel('File').setInputFiles({ name: 'run.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('MZ') })
  await page.getByRole('button', { name: 'Upload' }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('not allowed')
})

test('apply a cadence to a contact creates upcoming tasks', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Contacts' }).click()
  await page.locator('tbody tr').nth(3).click()
  await page.getByLabel('Apply cadence').selectOption({ label: 'Owner prospecting (90-day)' })
  await expect(page.getByText(/tasks created|Already applied/)).toBeVisible()
  await expect(page.getByText('Upcoming')).toBeVisible()
})

test('mentions notify the mentioned user and the bell shows it', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Contacts' }).click()
  await page.locator('tbody tr').first().click()
  await page.getByRole('button', { name: 'Note', exact: true }).click()
  await page.getByLabel('Note', { exact: true }).fill('@[Kevin Park] please follow up on this one')
  await page.getByRole('button', { name: 'Save note' }).click()
  await page.getByLabel('Sign out').click()
  await login(page, 'kevin@resha.group')
  await expect(page.getByTestId('unread-badge')).toBeVisible()
  await page.getByLabel('Notifications').click()
  await expect(page.getByText('please follow up on this one').first()).toBeVisible()
})
