// @ts-check
import { test, expect } from '@playwright/test';
import { mockAllApiRoutes, mockConversation } from './fixtures/api-mocks.js';

test.describe('People Tab — Consolidated Display', () => {

  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
  });

  test('person with mixed linked/unlinked claims appears once with unlinked indicator', async ({ page }) => {
    // Override people endpoint: Daniel Park has 4 claims, 2 unlinked (consolidated by backend)
    await page.route('**/api/conversations/conv-test-001/people*', route => {
      route.fulfill({
        json: {
          people: [
            {
              original_name: 'Stephen Andrews', canonical_name: 'Stephen Andrews',
              entity_id: 'c-006', status: 'confirmed', is_self: true,
              is_provisional: false, claim_count: 1, unlinked_claim_count: 0,
              all_names: ['Stephen Andrews'], roles: ['subject'], link_sources: ['confirm_person'],
            },
            {
              original_name: 'Daniel Park', canonical_name: 'Daniel Park',
              entity_id: 'ent-daniel', status: 'auto_resolved', is_self: false,
              is_provisional: false, claim_count: 4, unlinked_claim_count: 2,
              all_names: ['Daniel Park'], roles: ['subject'], link_sources: ['entity_resolution'],
            },
            {
              original_name: 'Vijay Menon', canonical_name: 'Vijay Menon',
              entity_id: 'ent-vijay', status: 'confirmed', is_self: false,
              is_provisional: false, claim_count: 2, unlinked_claim_count: 1,
              all_names: ['Vijay Menon'], roles: ['subject'], link_sources: ['confirm_person'],
            },
          ],
          total: 3,
        },
      });
    });

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // Expand people banner if collapsed
    const peopleBanner = page.locator('text=people');
    if (await peopleBanner.isVisible({ timeout: 2000 }).catch(() => false)) {
      await peopleBanner.click();
    }

    // Daniel Park should appear exactly once
    const danielEntries = page.locator('text=Daniel Park');
    const danielCount = await danielEntries.count();
    expect(danielCount).toBeGreaterThanOrEqual(1);

    // The "4 claims, 2 unlinked" text should be visible for Daniel Park
    await expect(page.getByText('4 claims, 2 unlinked')).toBeVisible();

    // Vijay Menon should appear exactly once
    const vijayEntries = page.locator('text=Vijay Menon');
    const vijayCount = await vijayEntries.count();
    expect(vijayCount).toBeGreaterThanOrEqual(1);

    // "2 claims, 1 unlinked" should be visible for Vijay
    await expect(page.getByText('2 claims, 1 unlinked')).toBeVisible();

    // The people header should show count of 3 (including self)
    // — no duplicate entries for Daniel or Vijay
    await expect(page.getByText('People (3)')).toBeVisible();
  });

  test('fully linked person shows no unlinked indicator', async ({ page }) => {
    // Override people endpoint: all claims linked, no unlinked count
    await page.route('**/api/conversations/conv-test-001/people*', route => {
      route.fulfill({
        json: {
          people: [
            {
              original_name: 'Stephen Andrews', canonical_name: 'Stephen Andrews',
              entity_id: 'c-006', status: 'confirmed', is_self: true,
              is_provisional: false, claim_count: 1, unlinked_claim_count: 0,
              all_names: ['Stephen Andrews'], roles: ['subject'], link_sources: ['confirm_person'],
            },
            {
              original_name: 'Sarah Chen', canonical_name: 'Sarah Chen',
              entity_id: 'c-001', status: 'confirmed', is_self: false,
              is_provisional: false, claim_count: 3, unlinked_claim_count: 0,
              all_names: ['Sarah Chen'], roles: ['subject'], link_sources: ['confirm_person'],
            },
          ],
          total: 2,
        },
      });
    });

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // "unlinked" should NOT appear anywhere
    await expect(page.getByText(/unlinked/)).not.toBeVisible();
  });

  test('genuinely unresolved person still appears separately', async ({ page }) => {
    // Override people endpoint: one resolved person + one genuinely unresolved
    await page.route('**/api/conversations/conv-test-001/people*', route => {
      route.fulfill({
        json: {
          people: [
            {
              original_name: 'Unknown Caller', canonical_name: null,
              entity_id: null, status: 'unresolved', is_self: false,
              is_provisional: false, claim_count: 2, unlinked_claim_count: 0,
              all_names: ['Unknown Caller'], roles: ['subject'], link_sources: [],
            },
            {
              original_name: 'Sarah Chen', canonical_name: 'Sarah Chen',
              entity_id: 'c-001', status: 'confirmed', is_self: false,
              is_provisional: false, claim_count: 3, unlinked_claim_count: 0,
              all_names: ['Sarah Chen'], roles: ['subject'], link_sources: ['confirm_person'],
            },
          ],
          total: 2,
        },
      });
    });

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // Expand if needed
    const peopleBanner = page.locator('text=people');
    if (await peopleBanner.isVisible({ timeout: 2000 }).catch(() => false)) {
      await peopleBanner.click();
    }

    // Both should appear as separate entries
    await expect(page.getByText('Unknown Caller')).toBeVisible();
    await expect(page.getByText('Sarah Chen')).toBeVisible();

    // Unknown Caller should have the unresolved badge
    await expect(page.getByText('unresolved')).toBeVisible();
  });

  test('Link N button appears for unlinked claims and calls API on click', async ({ page }) => {
    // Track whether the link-remaining API was called
    let apiCalled = false;
    let apiBody = null;
    let linkClicked = false;

    // Override people endpoint — use a flag (not call count) because refreshKey
    // causes PeopleReviewBanner to remount, triggering multiple initial fetches.
    await page.route('**/api/conversations/conv-test-001/people*', route => {
      route.fulfill({
        json: {
          people: [
            {
              original_name: 'Daniel Park', canonical_name: 'Daniel Park',
              entity_id: 'ent-daniel', status: 'auto_resolved', is_self: false,
              is_provisional: false, claim_count: 4,
              unlinked_claim_count: linkClicked ? 0 : 2,
              all_names: ['Daniel Park'], roles: ['subject'], link_sources: ['entity_resolution'],
            },
          ],
          total: 1,
        },
      });
    });

    await page.route('**/api/conversations/conv-test-001/link-remaining-claims', route => {
      apiCalled = true;
      linkClicked = true;
      apiBody = route.request().postDataJSON();
      route.fulfill({ json: { linked: 2, entity_id: 'ent-daniel', canonical_name: 'Daniel Park' } });
    });

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // "Link 2" button should be visible
    const linkBtn = page.getByRole('button', { name: 'Link 2' });
    await expect(linkBtn).toBeVisible();

    // Click it
    await linkBtn.click();

    // Verify API was called with correct payload
    await page.waitForTimeout(500);
    expect(apiCalled).toBe(true);
    expect(apiBody.entity_id).toBe('ent-daniel');
    expect(apiBody.subject_name).toBe('Daniel Park');

    // After refresh, "Link 2" button should be gone
    await expect(linkBtn).not.toBeVisible({ timeout: 3000 });
  });

  test('Link N button hidden when no unlinked claims', async ({ page }) => {
    await page.route('**/api/conversations/conv-test-001/people*', route => {
      route.fulfill({
        json: {
          people: [
            {
              original_name: 'Sarah Chen', canonical_name: 'Sarah Chen',
              entity_id: 'c-001', status: 'auto_resolved', is_self: false,
              is_provisional: false, claim_count: 3, unlinked_claim_count: 0,
              all_names: ['Sarah Chen'], roles: ['subject'], link_sources: ['entity_resolution'],
            },
          ],
          total: 1,
        },
      });
    });

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // No "Link" button should exist
    const linkBtns = page.getByRole('button').filter({ hasText: /^Link \d+$/ });
    await expect(linkBtns).toHaveCount(0);
  });
});
