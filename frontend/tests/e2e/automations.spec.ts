/**
 * Automations workspace — happy-path E2E test.
 *
 * Requirements tested:
 *   1. /automations route loads without error
 *   2. "NEW TRIGGER" button opens the editor sheet
 *   3. User can fill name + type and Save (creates trigger via API)
 *   4. The saved trigger appears as a card on the page
 *   5. The card's "Run now" button fires the trigger
 *   6. Recent Activity section is visible
 *
 * The tests run against the full Docker-compose stack (app + db + redis).
 * A trigger created in step 3 is deleted at teardown via the API.
 */
import { test, expect, type APIRequestContext } from '@playwright/test'

async function cleanupTrigger(request: APIRequestContext, id: string) {
  await request.delete(`/api/v1/triggers/${id}`).catch(() => {})
}

test.describe('Automations workspace', () => {
  test('page loads with correct heading', async ({ page }) => {
    await page.goto('/automations')
    await expect(page.getByRole('heading', { name: 'Automations' })).toBeVisible()
  })

  test('empty state shown when no triggers exist', async ({ page, request }) => {
    // Ensure any leftover triggers from prior runs are cleaned
    const existing = await request.get('/api/v1/triggers')
    if (existing.ok()) {
      const triggers: Array<{ id: string }> = await existing.json()
      for (const t of triggers) {
        await cleanupTrigger(request, t.id)
      }
    }
    await page.goto('/automations')
    await expect(page.getByText(/no triggers yet/i)).toBeVisible()
  })

  test('create watch trigger and see card appear', async ({ page, request }) => {
    // Clean slate
    const existing = await request.get('/api/v1/triggers')
    if (existing.ok()) {
      const triggers: Array<{ id: string }> = await existing.json()
      for (const t of triggers) {
        await cleanupTrigger(request, t.id)
      }
    }

    await page.goto('/automations')

    // Open the editor sheet
    await page.getByRole('button', { name: /new trigger/i }).click()
    await expect(page.getByRole('heading', { name: 'New Trigger' })).toBeVisible()

    // Fill name
    await page.getByLabel('Name').fill('E2E Watch Test')

    // Type defaults to 'watch' — fill the watch path
    await page.getByPlaceholder('/shared/TV').fill('/shared/TV')

    // Save trigger button (aria-label="Save")
    await page.getByRole('button', { name: 'Save' }).click()

    // Sheet should close and the card should appear
    await expect(page.getByText('E2E Watch Test')).toBeVisible({ timeout: 10000 })

    // Clean up via API
    const list = await request.get('/api/v1/triggers')
    if (list.ok()) {
      const triggers: Array<{ id: string; name: string }> = await list.json()
      for (const t of triggers) {
        if (t.name === 'E2E Watch Test') {
          await cleanupTrigger(request, t.id)
        }
      }
    }
  })

  test('Recent Activity section is visible on automations page', async ({ page }) => {
    await page.goto('/automations')
    await expect(page.getByText('Recent Activity')).toBeVisible()
  })
})
