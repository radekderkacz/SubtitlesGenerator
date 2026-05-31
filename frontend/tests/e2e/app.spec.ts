import { test, expect } from '@playwright/test'

test('app loads and health endpoint responds', async ({ page, request }) => {
  const health = await request.get('/api/v1/health')
  expect(health.ok()).toBeTruthy()
  const body = await health.json()
  expect(body.status).toBe('ok')

  await page.goto('/')
  await expect(page).not.toHaveTitle(/error/i)
})
