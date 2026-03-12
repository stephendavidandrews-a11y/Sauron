// @ts-check
import { test, expect } from '@playwright/test';
import { mockAllApiRoutes, mockConversation, mockReviewResult, mockPeople } from './fixtures/api-mocks.js';

test.describe('Review Flow — Trust-Critical Path', () => {

  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
  });

  // ═══════════════════════════════════════════════════
  // 1. REVIEW QUEUE SMOKE (3 tests)
  // ═══════════════════════════════════════════════════

  test('Review page loads and shows queue', async ({ page }) => {
    await page.goto('/review');
    await expect(page.getByTestId('review-page')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Review', exact: true })).toBeVisible();
    // Should show at least one conversation in claim review bucket
    await expect(page.getByText('Weekly CFTC Enforcement Strategy')).toBeVisible();
  });

  test('queue shows conversation metadata', async ({ page }) => {
    await page.goto('/review');
    await expect(page.getByTestId('review-page')).toBeVisible();
    // Claim review bucket should show count
    await expect(page.getByText('Claim Review')).toBeVisible();
    // Conversation row should show the title
    await expect(page.getByText('Weekly CFTC Enforcement Strategy')).toBeVisible();
  });

  test('clicking a conversation opens ConversationDetail', async ({ page }) => {
    await page.goto('/review');
    await page.getByText('Weekly CFTC Enforcement Strategy').click();
    await expect(page.getByTestId('conversation-detail')).toBeVisible();
    await expect(page.getByText('Weekly CFTC Enforcement Strategy')).toBeVisible();
    await expect(page.getByTestId('mark-reviewed-btn')).toBeVisible();
  });

  // ═══════════════════════════════════════════════════
  // 2. CLAIM REVIEW SMOKE (3 tests)
  // ═══════════════════════════════════════════════════

  test('approve claim changes its visual state', async ({ page }) => {
    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // Switch to claims tab where claims are shown flat
    await page.getByTestId('tab-claims').click();

    const approveBtn = page.getByTestId('claim-approve-claim-001');
    await expect(approveBtn).toBeVisible();

    await approveBtn.click();

    // Claim should now show confirmed status badge
    const claimRow = page.getByTestId('claim-row-claim-001');
    await expect(claimRow.getByText('confirmed').first()).toBeVisible();

    // Approve button should be hidden (claim is now reviewed)
    await expect(approveBtn).not.toBeVisible();
  });

  test('defer claim changes its visual state', async ({ page }) => {
    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    await page.getByTestId('tab-claims').click();

    const deferBtn = page.getByTestId('claim-defer-claim-002');
    await expect(deferBtn).toBeVisible();

    await deferBtn.click();

    const claimRow = page.getByTestId('claim-row-claim-002');
    await expect(claimRow.getByText('deferred').first()).toBeVisible();

    // Defer button should be hidden
    await expect(deferBtn).not.toBeVisible();
  });

  test('approve calls POST /api/correct/approve-claim with correct payload', async ({ page }) => {
    let capturedBody = null;
    await page.route('**/api/correct/approve-claim', async route => {
      const request = route.request();
      capturedBody = JSON.parse(request.postData() || '{}');
      await route.fulfill({ json: { success: true } });
    });

    await page.goto('/review/conv-test-001');
    await page.getByTestId('tab-claims').click();
    await page.getByTestId('claim-approve-claim-001').click();

    // Wait for the confirmed badge
    await expect(page.getByTestId('claim-row-claim-001').getByText('confirmed').first()).toBeVisible();

    // Verify API was called with correct payload
    expect(capturedBody).not.toBeNull();
    expect(capturedBody.conversation_id).toBe('conv-test-001');
    expect(capturedBody.claim_id).toBe('claim-001');
  });

  // ═══════════════════════════════════════════════════
  // 3. TRANSCRIPT CORRECTION SMOKE (2 tests)
  // ═══════════════════════════════════════════════════

  test('transcript tab shows segments with speaker names', async ({ page }) => {
    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    await page.getByTestId('tab-transcript').click();

    // All 3 transcript segments should be visible
    await expect(page.getByText('Let me start with the position limits update.')).toBeVisible();
    await expect(page.getByText('We expect finalization by Q3 this year.')).toBeVisible();
    await expect(page.getByText('The comment period closes April 15th.')).toBeVisible();

    // Speaker names should be visible
    await expect(page.getByText('Stephen Andrews').first()).toBeVisible();
    await expect(page.getByText('Sarah Chen').first()).toBeVisible();
    await expect(page.getByText('Mark Weber').first()).toBeVisible();
  });

  test('speaker name is clickable for reassignment', async ({ page }) => {
    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    await page.getByTestId('tab-transcript').click();

    // Wait for transcript to load
    await expect(page.getByText('Let me start with the position limits update.')).toBeVisible();

    // Click speaker name — should open a dropdown for speaker reassignment
    // Speaker names are buttons in the transcript tab
    const speakerBtn = page.getByRole('button', { name: 'Stephen Andrews' }).first();
    await expect(speakerBtn).toBeVisible();
    await speakerBtn.click();

    // A search dropdown should appear for reassigning the speaker
    await expect(page.getByPlaceholder('Search...')).toBeVisible();
  });

  // ═══════════════════════════════════════════════════
  // 4. MARK-AS-REVIEWED CRITICAL PATH (3 tests)
  // ═══════════════════════════════════════════════════

  test('mark as reviewed sends POST and shows reviewed badge', async ({ page }) => {
    let reviewCalled = false;
    await page.route('**/api/conversations/conv-test-001/review', async route => {
      reviewCalled = true;
      await route.fulfill({ json: mockReviewResult });
    });

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('mark-reviewed-btn')).toBeVisible();

    await page.getByTestId('mark-reviewed-btn').click();

    // Should show reviewed badge
    await expect(page.getByTestId('reviewed-badge')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Reviewed')).toBeVisible();

    // Mark-reviewed button should be gone
    await expect(page.getByTestId('mark-reviewed-btn')).not.toBeVisible();

    // API was called
    expect(reviewCalled).toBe(true);
  });

  test('mark reviewed shows stats', async ({ page }) => {
    await page.goto('/review/conv-test-001');
    await page.getByTestId('mark-reviewed-btn').click();
    await expect(page.getByTestId('reviewed-badge')).toBeVisible({ timeout: 5000 });

    // Stats from mockReviewResult should appear
    await expect(page.getByText('2 approved')).toBeVisible();
    await expect(page.getByText('1 corrected')).toBeVisible();
    await expect(page.getByText('1 dismissed')).toBeVisible();
    await expect(page.getByText('3 beliefs affected')).toBeVisible();
  });

  test('discard button visible before review, hidden after', async ({ page }) => {
    await page.goto('/review/conv-test-001');

    // Discard visible on unreviewed conversation
    await expect(page.getByTestId('discard-btn')).toBeVisible();
    await expect(page.getByTestId('discard-btn')).toHaveText('✗ Discard');

    // Mark as reviewed
    await page.getByTestId('mark-reviewed-btn').click();
    await expect(page.getByTestId('reviewed-badge')).toBeVisible({ timeout: 5000 });

    // Discard should now be hidden
    await expect(page.getByTestId('discard-btn')).not.toBeVisible();
  });

  // ═══════════════════════════════════════════════════
  // SUPPORTING: Tabs, people, navigation
  // ═══════════════════════════════════════════════════

  test('conversation detail tabs are present and switchable', async ({ page }) => {
    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // All 5 tabs visible
    await expect(page.getByTestId('tab-episodes')).toBeVisible();
    await expect(page.getByTestId('tab-transcript')).toBeVisible();
    await expect(page.getByTestId('tab-claims')).toBeVisible();
    await expect(page.getByTestId('tab-summary')).toBeVisible();
    await expect(page.getByTestId('tab-raw')).toBeVisible();

    // Episodes tab is default — episode titles should be visible
    await expect(page.getByText('Position limits discussion')).toBeVisible();

    // Switch to transcript tab
    await page.getByTestId('tab-transcript').click();
    await expect(page.getByText('Let me start with the position limits update.')).toBeVisible();

    // Switch to claims tab
    await page.getByTestId('tab-claims').click();
    await expect(page.getByText('Position limits will be finalized by Q3 2026.')).toBeVisible();
  });

  test('people review banner shows auto-resolved requiring confirmation', async ({ page }) => {
    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // People banner should show — Sarah Chen is auto_resolved
    await expect(page.getByText('People')).toBeVisible();
    await expect(page.getByText('auto-resolved')).toBeVisible();
    await expect(page.getByText('Sarah Chen')).toBeVisible();
  });

  test('back link returns to review queue', async ({ page }) => {
    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    await page.getByText('← Back to review').click();
    await expect(page.getByTestId('review-page')).toBeVisible();
  });


  // ═══════════════════════════════════════════════════
  // 5. FAILURE PATH — ROLLBACK + ERROR FEEDBACK (3 tests)
  // ═══════════════════════════════════════════════════

  test('approve-all API failure does not leave claims visually confirmed', async ({ page }) => {
    // Override the bulk approve endpoint to return 500
    await page.route('**/api/correct/approve-claims-bulk', route =>
      route.fulfill({ status: 500, json: { error: 'server_error' } }));

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // Episodes tab is default; click episode header to expand it
    await page.getByText('Position limits discussion').click();

    // Wait for claims to render inside the expanded episode
    const approveAllBtn = page.getByTestId('approve-all-ep-001');
    await expect(approveAllBtn).toBeVisible({ timeout: 3000 });
    await approveAllBtn.click();

    // Error banner should appear
    await expect(page.getByTestId('action-error-banner')).toBeVisible({ timeout: 3000 });
    await expect(page.getByTestId('action-error-banner')).toContainText('Approve all failed');

    // Claims should NOT be marked as confirmed — approve buttons should still be visible
    // (claim action buttons inside episodes tab use the same testids)
    const claim1Approve = page.getByTestId('claim-approve-claim-001');
    await expect(claim1Approve).toBeVisible();
  });

  test('ClaimsTab approve API failure does not leave claim visually confirmed', async ({ page }) => {
    // Override single approve endpoint to return 500
    await page.route('**/api/correct/approve-claim', route =>
      route.fulfill({ status: 500, json: { error: 'server_error' } }));

    await page.goto('/review/conv-test-001');
    await expect(page.getByTestId('conversation-detail')).toBeVisible();

    // Switch to claims tab
    await page.getByTestId('tab-claims').click();

    const approveBtn = page.getByTestId('claim-approve-claim-001');
    await expect(approveBtn).toBeVisible();
    await approveBtn.click();

    // Error banner should appear
    await expect(page.getByTestId('action-error-banner')).toBeVisible({ timeout: 3000 });
    await expect(page.getByTestId('action-error-banner')).toContainText('Approve failed');

    // Claim should NOT show confirmed badge — approve button should still be there
    await expect(approveBtn).toBeVisible();
    const claimRow = page.getByTestId('claim-row-claim-001');
    await expect(claimRow.getByText('confirmed')).not.toBeVisible();
  });

  test('error banner is dismissible by clicking close button', async ({ page }) => {
    // Override approve to fail
    await page.route('**/api/correct/approve-claim', route =>
      route.fulfill({ status: 500, json: { error: 'server_error' } }));

    await page.goto('/review/conv-test-001');
    await page.getByTestId('tab-claims').click();

    // Trigger error
    await page.getByTestId('claim-approve-claim-001').click();
    await expect(page.getByTestId('action-error-banner')).toBeVisible({ timeout: 3000 });

    // Click the close button (✕)
    await page.getByTestId('action-error-banner').getByRole('button').click();

    // Banner should disappear
    await expect(page.getByTestId('action-error-banner')).not.toBeVisible();
  });
});
