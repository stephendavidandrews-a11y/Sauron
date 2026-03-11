/**
 * Reusable API mock handlers for Playwright e2e tests.
 * Intercepts /api/* routes with deterministic data so tests
 * run offline against the Vite dev server without a real backend.
 *
 * IMPORTANT: Playwright routes match LAST-REGISTERED-FIRST.
 * Register catch-all FIRST (lowest priority), specific routes AFTER (highest priority).
 */

export const mockConversation = {
  conversation: {
    id: 'conv-test-001',
    title: 'Weekly CFTC Enforcement Strategy',
    source: 'iphone',
    captured_at: '2026-03-10T10:00:00Z',
    created_at: '2026-03-10T10:00:00Z',
    processing_status: 'awaiting_claim_review',
    reviewed_at: null,
    duration_seconds: 2400,
    context_classification: 'professional',
    episode_count: 2,
    claim_count: 4,
    manual_note: null,
  },
  episodes: [
    { id: 'ep-001', episode_number: 1, title: 'Position limits discussion', summary: 'Discussed new position limits framework.', claim_count: 3 },
    { id: 'ep-002', episode_number: 2, title: 'Timeline review', summary: 'Reviewed enforcement timeline.', claim_count: 1 },
  ],
  claims: [
    {
      id: 'claim-001', claim_type: 'position', claim_text: 'Position limits will be finalized by Q3 2026.',
      confidence: 0.92, episode_id: 'ep-001', subject_name: 'Sarah Chen', subject_entity_id: 'c-001',
      linked_entity_name: 'Sarah Chen', review_status: null, entities: [{ entity_id: 'c-001', entity_name: 'Sarah Chen', role: 'subject' }],
      display_overrides: null,
    },
    {
      id: 'claim-002', claim_type: 'fact', claim_text: 'The comment period closes on April 15.',
      confidence: 0.88, episode_id: 'ep-001', subject_name: 'Mark Weber', subject_entity_id: 'c-002',
      linked_entity_name: 'Mark Weber', review_status: null, entities: [{ entity_id: 'c-002', entity_name: 'Mark Weber', role: 'subject' }],
      display_overrides: null,
    },
    {
      id: 'claim-003', claim_type: 'commitment', claim_text: 'I will send the draft memo by Friday.',
      confidence: 0.95, episode_id: 'ep-001', subject_name: 'Stephen Andrews', subject_entity_id: 'c-006',
      linked_entity_name: 'Stephen Andrews', review_status: null, entities: [{ entity_id: 'c-006', entity_name: 'Stephen Andrews', role: 'subject' }],
      display_overrides: null, commitment_deadline: '2026-03-14', commitment_owner: 'Stephen Andrews',
    },
    {
      id: 'claim-004', claim_type: 'position', claim_text: 'Phased implementation is preferred over big-bang.',
      confidence: 0.78, episode_id: 'ep-002', subject_name: 'Sarah Chen', subject_entity_id: 'c-001',
      linked_entity_name: 'Sarah Chen', review_status: null, entities: [{ entity_id: 'c-001', entity_name: 'Sarah Chen', role: 'subject' }],
      display_overrides: null,
    },
  ],
  transcript: [
    { id: 'seg-001', speaker_label: 'SPEAKER_00', speaker_name: 'Stephen Andrews', speaker_id: 'c-006', text: 'Let me start with the position limits update.', start_time: 0, end_time: 4.2 },
    { id: 'seg-002', speaker_label: 'SPEAKER_01', speaker_name: 'Sarah Chen', speaker_id: 'c-001', text: 'We expect finalization by Q3 this year.', start_time: 4.5, end_time: 8.1 },
    { id: 'seg-003', speaker_label: 'SPEAKER_02', speaker_name: 'Mark Weber', speaker_id: 'c-002', text: 'The comment period closes April 15th.', start_time: 8.5, end_time: 12.0 },
  ],
  extraction: { synthesis: { word_voice_alignment: 'aligned' } },
  belief_updates: [],
};

export const mockPeople = {
  people: [
    { original_name: 'Stephen Andrews', canonical_name: 'Stephen Andrews', entity_id: 'c-006', status: 'confirmed', is_self: true, is_provisional: false, claim_count: 1 },
    { original_name: 'Sarah Chen', canonical_name: 'Sarah Chen', entity_id: 'c-001', status: 'auto_resolved', is_self: false, is_provisional: false, claim_count: 2 },
    { original_name: 'Mark Weber', canonical_name: 'Mark Weber', entity_id: 'c-002', status: 'confirmed', is_self: false, is_provisional: false, claim_count: 1 },
  ],
};

export const mockQueueCounts = {
  speaker_review: 0,
  triage_review: 0,
  claim_review: 1,
  processing: 0,
  pending: 0,
};

export const mockNeedsReview = {
  conversations: [
    {
      id: 'conv-test-001',
      title: 'Weekly CFTC Enforcement Strategy',
      source: 'iphone',
      captured_at: '2026-03-10T10:00:00Z',
      processing_status: 'awaiting_claim_review',
      reviewed_at: null,
      duration_seconds: 2400,
      episode_count: 2,
      claim_count: 4,
    },
  ],
};

export const mockContacts = {
  contacts: [
    { id: 'c-001', canonical_name: 'Sarah Chen', email: 'sarah@example.com', is_confirmed: 1 },
    { id: 'c-002', canonical_name: 'Mark Weber', email: 'mark@example.com', is_confirmed: 1 },
    { id: 'c-006', canonical_name: 'Stephen Andrews', email: 'stephen@example.com', is_confirmed: 1 },
  ],
};

export const mockRoutingPreview = {
  objects: {},
  total_objects: 0,
  routing_blocked: false,
};

export const mockRelationalClaims = {
  relational_claims: [],
};

export const mockReviewResult = {
  stats: { approved: 2, corrections: 1, dismissed: 1, deferred: 0, beliefs_affected: 3 },
};

/**
 * Set up all API route mocks for a page instance.
 *
 * ROUTE PRIORITY: Playwright matches routes LAST-REGISTERED-FIRST.
 * Register catch-all FIRST (lowest priority), specific routes AFTER.
 */
export async function mockAllApiRoutes(page) {
  // ─── CATCH-ALL (lowest priority — registered first) ───
  await page.route('**/api/**', route => {
    route.fulfill({ json: {} });
  });

  // ─── Review page endpoints ───
  await page.route('**/api/conversations/queue-counts', route =>
    route.fulfill({ json: mockQueueCounts }));

  await page.route('**/api/conversations/needs-review*', route =>
    route.fulfill({ json: mockNeedsReview }));

  // Review page also fetches all conversations
  await page.route('**/api/conversations?*', route =>
    route.fulfill({ json: { conversations: mockNeedsReview.conversations, total: 1 } }));

  // ─── Beliefs/Learning (Review page sidebar) ───
  await page.route('**/api/beliefs/stats', route =>
    route.fulfill({ json: { total: 0, under_review: 0, contested: 0 } }));

  await page.route('**/api/beliefs/resynthesis/pending', route =>
    route.fulfill({ json: { pending: 0 } }));

  await page.route('**/api/learning/dashboard', route =>
    route.fulfill({ json: { corrections_count: 0, amendments_count: 0 } }));

  // ─── Graph ───
  await page.route('**/api/graph?*', route =>
    route.fulfill({ json: { edges: [] } }));

  // Relational claims (actual URL path the app uses)
  await page.route('**/api/graph/unresolved-relational*', route =>
    route.fulfill({ json: mockRelationalClaims }));

  // ─── Conversation detail ───
  await page.route('**/api/conversations/conv-test-001', route =>
    route.fulfill({ json: mockConversation }));

  // People
  await page.route('**/api/conversations/conv-test-001/people*', route =>
    route.fulfill({ json: mockPeople }));

  // Routing preview
  await page.route('**/api/conversations/conv-test-001/routing-preview', route =>
    route.fulfill({ json: mockRoutingPreview }));

  // Review action (POST)
  await page.route('**/api/conversations/conv-test-001/review', route =>
    route.fulfill({ json: mockReviewResult }));

  // ─── Correction endpoints (actual paths from src/api.js) ───
  await page.route('**/api/correct/approve-claim', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/approve-claims-bulk', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/dismiss-claim', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/defer-claim', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/claim', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/extraction', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/speaker', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/entity-link*', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/save-relationship', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/commitment-meta', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/correct/error-types', route =>
    route.fulfill({ json: { error_types: [] } }));

  // People actions (confirm-person, skip-person, etc.)
  await page.route('**/api/conversations/conv-test-001/confirm-person', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/conversations/conv-test-001/skip-person', route =>
    route.fulfill({ json: { success: true } }));

  await page.route('**/api/conversations/conv-test-001/dismiss-person', route =>
    route.fulfill({ json: { success: true } }));

  // Pipeline confirm speakers
  await page.route('**/api/pipeline/confirm-speakers/*', route =>
    route.fulfill({ json: { success: true } }));

  // Contacts
  await page.route('**/api/contacts*', route =>
    route.fulfill({ json: mockContacts }));

  // Health
  await page.route('**/api/health', route =>
    route.fulfill({ json: { status: 'ok' } }));
}
