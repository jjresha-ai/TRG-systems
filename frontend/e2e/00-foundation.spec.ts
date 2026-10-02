import { expect, test } from '@playwright/test'
import { login } from './helpers'

test('rejects a bad password', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill('jim@resha.group')
  await page.getByLabel('Password').fill('nope')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toContainText('Invalid')
})

test('login shows the live build home with all stages', async ({ page }) => {
  await login(page)
  await expect(page.getByRole('heading', { name: /Welcome, Jim/ })).toBeVisible()
  await page.getByRole('tab', { name: 'Build progress' }).click()
  await expect(page.getByText('Contacts, Companies & Properties')).toBeVisible()
  await expect(page.getByText('Hardening')).toBeVisible()
})

test('an unknown route says so instead of rendering a blank page', async ({ page }) => {
  await login(page)
  await page.goto('/no-such-screen')
  await expect(page.getByText('This page does not exist.')).toBeVisible()
})
