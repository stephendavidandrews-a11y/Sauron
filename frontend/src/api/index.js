// Domain modules
import { conversationsApi } from './conversations';
import { correctionsApi } from './corrections';
import { beliefsApi } from './beliefs';
import { contactsApi } from './contacts';
import { searchApi } from './search';
import { pipelineApi } from './pipeline';
import { learningApi } from './learning';
import { miscApi } from './misc';

// Unified api object (backward-compatible with original api.js)
export const api = {
  ...miscApi,
  ...conversationsApi,
  ...correctionsApi,
  ...beliefsApi,
  ...contactsApi,
  ...searchApi,
  ...pipelineApi,
  ...learningApi,
};

// Re-export named functions (used by some components)
export { clearContactsCache } from './client';
export { fetchRoutingSummary, fetchPendingRoutes, fetchGraphEdges, updateGraphEdge, confirmGraphEdge, dismissGraphEdge, createGraphEdge } from './routing';
export { fetchProvisionalOrgs, approveProvisionalOrg, mergeProvisionalOrg, dismissProvisionalOrg, searchNetworkingOrgs } from './orgs';
export { fetchTextPendingContacts, approveTextContact, dismissTextContact, deferTextContact, triggerTextSync, fetchTextStatus, fetchTextThreads } from './text';
