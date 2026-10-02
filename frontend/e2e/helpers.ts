import { expect, type Page } from '@playwright/test'

export async function login(page: Page, email = 'jim@resha.group') {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('demo1234')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Live build in progress')).toBeVisible()
}
