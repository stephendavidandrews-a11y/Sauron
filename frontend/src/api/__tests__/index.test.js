import { describe, it, expect, vi } from "vitest";

// Mock all sub-modules that index.js imports
vi.mock("../conversations", () => ({ conversationsApi: { fetchConversations: vi.fn() } }));
vi.mock("../corrections", () => ({ correctionsApi: { fetchCorrections: vi.fn() } }));
vi.mock("../beliefs", () => ({ beliefsApi: { fetchBeliefs: vi.fn() } }));
vi.mock("../contacts", () => ({ contactsApi: { fetchContacts: vi.fn() } }));
vi.mock("../search", () => ({ searchApi: { semanticSearch: vi.fn() } }));
vi.mock("../pipeline", () => ({ pipelineApi: { runPipeline: vi.fn() } }));
vi.mock("../learning", () => ({ learningApi: { fetchAmendments: vi.fn() } }));
vi.mock("../misc", () => ({ miscApi: { fetchHealth: vi.fn() } }));
vi.mock("../client", () => ({ clearContactsCache: vi.fn() }));
vi.mock("../routing", () => ({
  fetchRoutingSummary: vi.fn(),
  fetchPendingRoutes: vi.fn(),
  fetchGraphEdges: vi.fn(),
  updateGraphEdge: vi.fn(),
  confirmGraphEdge: vi.fn(),
  dismissGraphEdge: vi.fn(),
  createGraphEdge: vi.fn(),
}));
vi.mock("../orgs", () => ({
  fetchProvisionalOrgs: vi.fn(),
  approveProvisionalOrg: vi.fn(),
  mergeProvisionalOrg: vi.fn(),
  dismissProvisionalOrg: vi.fn(),
  searchNetworkingOrgs: vi.fn(),
}));
vi.mock("../text", () => ({
  fetchTextPendingContacts: vi.fn(),
  approveTextContact: vi.fn(),
  dismissTextContact: vi.fn(),
  deferTextContact: vi.fn(),
  triggerTextSync: vi.fn(),
  fetchTextStatus: vi.fn(),
  fetchTextThreads: vi.fn(),
}));

const {
  api,
  clearContactsCache,
  fetchRoutingSummary,
  fetchPendingRoutes,
  fetchGraphEdges,
  updateGraphEdge,
  confirmGraphEdge,
  dismissGraphEdge,
  createGraphEdge,
  fetchProvisionalOrgs,
  approveProvisionalOrg,
  mergeProvisionalOrg,
  dismissProvisionalOrg,
  searchNetworkingOrgs,
  fetchTextPendingContacts,
  approveTextContact,
  dismissTextContact,
  deferTextContact,
  triggerTextSync,
  fetchTextStatus,
  fetchTextThreads,
} = await import("../index");

describe("api barrel exports", () => {
  it("api object is defined and has methods from sub-modules", () => {
    expect(api).toBeDefined();
    expect(typeof api).toBe("object");
    // Spot-check a few methods from different sub-modules
    expect(typeof api.fetchConversations).toBe("function");
    expect(typeof api.fetchCorrections).toBe("function");
    expect(typeof api.fetchBeliefs).toBe("function");
    expect(typeof api.fetchContacts).toBe("function");
    expect(typeof api.semanticSearch).toBe("function");
    expect(typeof api.runPipeline).toBe("function");
    expect(typeof api.fetchAmendments).toBe("function");
    expect(typeof api.fetchHealth).toBe("function");
  });

  it("named routing exports are functions", () => {
    expect(typeof fetchRoutingSummary).toBe("function");
    expect(typeof fetchPendingRoutes).toBe("function");
    expect(typeof fetchGraphEdges).toBe("function");
    expect(typeof updateGraphEdge).toBe("function");
    expect(typeof confirmGraphEdge).toBe("function");
    expect(typeof dismissGraphEdge).toBe("function");
    expect(typeof createGraphEdge).toBe("function");
  });

  it("named org exports are functions", () => {
    expect(typeof fetchProvisionalOrgs).toBe("function");
    expect(typeof approveProvisionalOrg).toBe("function");
    expect(typeof mergeProvisionalOrg).toBe("function");
    expect(typeof dismissProvisionalOrg).toBe("function");
    expect(typeof searchNetworkingOrgs).toBe("function");
  });

  it("named text exports are functions", () => {
    expect(typeof fetchTextPendingContacts).toBe("function");
    expect(typeof approveTextContact).toBe("function");
    expect(typeof dismissTextContact).toBe("function");
    expect(typeof deferTextContact).toBe("function");
    expect(typeof triggerTextSync).toBe("function");
    expect(typeof fetchTextStatus).toBe("function");
    expect(typeof fetchTextThreads).toBe("function");
  });

  it("clearContactsCache is re-exported from client", () => {
    expect(typeof clearContactsCache).toBe("function");
  });
});
