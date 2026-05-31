/**
 * Live-integration regression tests for the Automations editor.
 *
 * SAFETY: only touches triggers whose name begins with `TEST_PREFIX`.
 * Never list-and-delete "all triggers" the way the sibling
 * automations.spec.ts does — that pattern destroys real data.
 *
 * Run against a deployed instance:
 *   PLAYWRIGHT_BASE_URL=http://<your-host>:8000 \
 *     npx playwright test tests/e2e/automations-fixes.spec.ts
 */
import { test, expect, type APIRequestContext } from '@playwright/test'
import { randomUUID } from 'node:crypto'

const TEST_PREFIX = `E2E-FIX-${randomUUID().slice(0, 8)}`

async function cleanupByPrefix(request: APIRequestContext, prefix: string) {
  const res = await request.get('/api/v1/triggers')
  if (!res.ok()) return
  const triggers: Array<{ id: string; name: string }> = await res.json()
  for (const t of triggers) {
    if (t.name.startsWith(prefix)) {
      await request.delete(`/api/v1/triggers/${t.id}`).catch(() => {})
    }
  }
}

async function firstProfileName(request: APIRequestContext): Promise<string> {
  // The trigger backend rejects profile_name values not in Settings.profiles
  // (ProfileNotFoundError → 422), so the spec discovers a real one per-run
  // instead of hardcoding 'Default' (which doesn't exist on every install).
  const res = await request.get('/api/v1/settings')
  if (!res.ok()) throw new Error('cannot read settings to discover profile')
  const data = (await res.json()) as { profiles?: Array<{ name?: string }> }
  const name = data.profiles?.find((p) => p?.name)?.name
  if (!name) throw new Error('no profiles configured — cannot seed test triggers')
  return name
}

test.describe('Automations editor — regression suite', () => {
  test.afterEach(async ({ request }) => {
    await cleanupByPrefix(request, TEST_PREFIX)
  })

  test('Bug A: Edit on a freshly-saved trigger pre-fills the editor', async ({
    page,
    request,
  }) => {
    const profileName = await firstProfileName(request)
    const name = `${TEST_PREFIX}-A`
    // Seed via API (faster + no UI churn for the create step)
    const created = await request.post('/api/v1/triggers', {
      data: {
        name,
        type: 'watch',
        config: { path: '/shared/TV' },
        action: {
          profile_name: profileName,
          source_language: null,
          target_language: null,
          skip_if_srt: true,
        },
        file_filter: { type: 'all', value: null },
        enabled: true,
      },
    })
    expect(created.ok()).toBeTruthy()

    await page.goto('/automations')
    const card = page.getByTestId('trigger-card').filter({ hasText: name })
    await card.getByRole('button', { name: /^edit$/i }).click()

    await expect(page.getByRole('heading', { name: /^Edit Trigger$/i })).toBeVisible()
    await expect(page.getByLabel(/^name$/i)).toHaveValue(name)
  })

  test('Bug C: Switching between Edit on two triggers shows each one’s data', async ({
    page,
    request,
  }) => {
    const profileName = await firstProfileName(request)
    const nameA = `${TEST_PREFIX}-Ca`
    const nameB = `${TEST_PREFIX}-Cb`
    for (const [n, path] of [
      [nameA, '/shared/A'],
      [nameB, '/shared/B'],
    ]) {
      const r = await request.post('/api/v1/triggers', {
        data: {
          name: n,
          type: 'watch',
          config: { path },
          action: {
            profile_name: profileName,
            source_language: null,
            target_language: null,
            skip_if_srt: true,
          },
          file_filter: { type: 'all', value: null },
          enabled: true,
        },
      })
      expect(r.ok()).toBeTruthy()
    }

    await page.goto('/automations')

    const cardFor = (cardName: string) =>
      page.getByTestId('trigger-card').filter({ hasText: cardName })

    // Edit B first
    await cardFor(nameB).getByRole('button', { name: /^edit$/i }).click()
    await expect(page.getByLabel(/^name$/i)).toHaveValue(nameB)
    await page.getByRole('button', { name: /cancel/i }).click()

    // Then edit A
    await cardFor(nameA).getByRole('button', { name: /^edit$/i }).click()
    await expect(page.getByLabel(/^name$/i)).toHaveValue(nameA)
  })

  test('Bug B: "Scan existing files" toggle exposes the initial-scan affordance', async ({
    page,
  }) => {
    await page.goto('/automations')
    await page.getByRole('button', { name: /new trigger/i }).click()
    await expect(page.getByRole('heading', { name: /^New Trigger$/i })).toBeVisible()

    // Watch is the default type — the checkbox must be present
    await expect(
      page.getByRole('checkbox', { name: /scan existing files/i }),
    ).toBeVisible()
  })
})
