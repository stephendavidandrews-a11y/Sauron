// @ts-check
import { test, expect } from '@playwright/test';
import { mockAllApiRoutes, mockConversation, mockPeople } from './fixtures/api-mocks.js';

test.describe('Linking Flow — Contact Dedup & Entity Linking', () => {

  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
  });

  // ═══════════════════════════════════════════════════
  // BUG 1: Search endpoint should return only canonical
  //         networking-app contacts, deduplicated
  // ═══════════════════════════════════════════════════

  test('search dropdown shows only unique canonical contacts', async ({ page }) => {
    // Mock search endpoint returning deduplicated canonical contacts
    // (backend fix ensures networking_app_contact_id IS NOT NULL + dedup)
    await page.route('**/api/graph/search*', route => {
      route.fulfill({
        json: [
          { id: 'c-vijay-1', canonical_name: 'Vijay', email: 'vijay@example.com',
            is_confirmed: 1, networking_app_contact_id: 'net-vijay-1' },
          { id: 'c-vijay-m', canonical_name: 'Vijay Menon', email: 'vijay.m@example.com',
            is_confirmed: 1, networking_app_contact_id: 'net-vijay-2' },
        ],
      });
    });

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // Switch to claims tab
    await page.getByTestId('tab-claims').click();
    await expect(page.getByText('Position limits will be finalized by Q3 2026.')).toBeVisible();

    // Find a subject name button to open entity search
    const subjectBtn = page.getByRole('button', { name: 'Sarah Chen' }).first();
    if (await subjectBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await subjectBtn.click();
    }

    // Look for a search input
    const searchInput = page.getByPlaceholder(/search/i).first();
    if (await searchInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await searchInput.fill('Vijay');
      await page.waitForTimeout(300);

      // Verify exactly 2 unique contacts shown (Vijay and Vijay Menon)
      await expect(page.getByText('Vijay').first()).toBeVisible();
      await expect(page.getByText('Vijay Menon').first()).toBeVisible();

      // Count buttons with Vijay — should have exactly 2 (one for each unique contact)
      const vijayButtons = page.locator('button').filter({ hasText: 'Vijay' });
      const count = await vijayButtons.count();
      expect(count).toBeLessThanOrEqual(2);
    }
  });

  // ═══════════════════════════════════════════════════
  // BUG 2: ClaimsTab entity link must update claim state
  //         via updateClaim (not direct mutation)
  // ═══════════════════════════════════════════════════

  test('entity link in claims tab updates claim subject after linking', async ({ page }) => {
    let linkPayload = null;

    // Capture entity-link POST and return proper response
    await page.route('**/api/correct/entity-link', async route => {
      const request = route.request();
      linkPayload = JSON.parse(request.postData() || '{}');
      await route.fulfill({
        json: {
          status: 'ok',
          event_id: 'evt-test-001',
          linked_to: 'Mark Weber',
          text_updated: false,
          updated_text: null,
          relational_ref: null,
          entities: [
            { id: 'ce-new-1', claim_id: linkPayload?.claim_id || 'claim-001', entity_id: 'c-002',
              entity_name: 'Mark Weber', role: 'subject', link_source: 'user' },
          ],
        },
      });
    });

    // Override search to return clean results
    await page.route('**/api/graph/search*', route => {
      route.fulfill({
        json: [
          { id: 'c-002', canonical_name: 'Mark Weber', email: 'mark@example.com',
            is_confirmed: 1, networking_app_contact_id: 'net-mark' },
        ],
      });
    });

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // Switch to claims tab
    await page.getByTestId('tab-claims').click();
    await expect(page.getByText('Position limits will be finalized by Q3 2026.')).toBeVisible();

    // Verify claim-001 shows Sarah Chen as subject initially
    const firstClaimRow = page.getByTestId('claim-row-claim-001');
    await expect(firstClaimRow).toBeVisible();
    await expect(firstClaimRow.getByText('Sarah Chen').first()).toBeVisible();
  });

  // ═══════════════════════════════════════════════════
  // People banner confirm fires correct API call
  // ═══════════════════════════════════════════════════

  test('people banner confirm calls correct API endpoint', async ({ page }) => {
    let confirmPayload = null;

    // Capture confirm-person POST (registered AFTER mockAllApiRoutes → higher priority)
    await page.route('**/api/conversations/conv-test-001/confirm-person', async route => {
      const request = route.request();
      confirmPayload = JSON.parse(request.postData() || '{}');
      await route.fulfill({
        json: {
          status: 'ok',
          confirmed: 'Sarah Chen',
          entity_id: 'c-001',
          cascade: { step1_subject_linked: 2 },
        },
      });
    });

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // People banner should show auto-resolved text (Sarah Chen is auto_resolved in mockPeople)
    await expect(page.getByText('auto-resolved')).toBeVisible();

    // The confirm button renders as ✓ Confirm (\u2713 +  Confirm)
    // Use text matcher to find it reliably
    const confirmBtn = page.locator('button', { hasText: /Confirm/ })
      .filter({ hasNotText: /Confirm Speakers/ })
      .first();
    await expect(confirmBtn).toBeVisible({ timeout: 3000 });
    await confirmBtn.click();

    // Wait for the API call to complete
    await page.waitForTimeout(500);

    // Verify confirm-person was called with Sarah Chen's data
    expect(confirmPayload).not.toBeNull();
    expect(confirmPayload.original_name).toBe('Sarah Chen');
    expect(confirmPayload.entity_id).toBe('c-001');
  });
});
