import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock tripwires before importing client
vi.mock("../../utils/tripwires", () => ({
  tripwire: {
    checkForSemantic200Error: vi.fn(),
    assertShape: vi.fn(),
    warn: vi.fn(),
    getWarnings: vi.fn(() => []),
    clearWarnings: vi.fn(),
  },
}));

// Mock import.meta.env
vi.stubEnv("VITE_SAURON_API_KEY", "test-key-123");

const { fetchJSON, getCachedContacts, clearContactsCache } = await import("../client");

describe("fetchJSON", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    clearContactsCache();
  });

  it("adds API key header when VITE_SAURON_API_KEY is set", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ data: "ok" }),
    });

    await fetchJSON("/test");

    expect(fetch).toHaveBeenCalledWith(
      "/api/test",
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-API-Key": "test-key-123",
          "Content-Type": "application/json",
        }),
      })
    );
  });

  it("throws on non-200 responses with status and body", async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 404,
      text: () => Promise.resolve("Not Found"),
    });

    await expect(fetchJSON("/missing")).rejects.toThrow("404: Not Found");
  });

  it("returns parsed JSON on success", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ items: [1, 2, 3] }),
    });

    const result = await fetchJSON("/items");
    expect(result).toEqual({ items: [1, 2, 3] });
  });
});

describe("contacts cache", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    clearContactsCache();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("getCachedContacts fetches on first call", async () => {
    const mockData = [{ id: 1, name: "Alice" }];
    fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    });

    const result = await getCachedContacts();
    expect(result).toEqual(mockData);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("getCachedContacts returns cached data on second call within TTL", async () => {
    const mockData = [{ id: 1, name: "Alice" }];
    fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    });

    await getCachedContacts();
    const result = await getCachedContacts();

    expect(result).toEqual(mockData);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("getCachedContacts re-fetches after TTL expires", async () => {
    vi.useFakeTimers();
    const data1 = [{ id: 1 }];
    const data2 = [{ id: 2 }];
    fetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(data1) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(data2) });

    await getCachedContacts();
    // Advance past TTL (5 minutes)
    vi.advanceTimersByTime(5 * 60 * 1000 + 1);
    const result = await getCachedContacts();

    expect(result).toEqual(data2);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("clearContactsCache forces re-fetch", async () => {
    const data1 = [{ id: 1 }];
    const data2 = [{ id: 2 }];
    fetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(data1) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(data2) });

    await getCachedContacts();
    clearContactsCache();
    const result = await getCachedContacts();

    expect(result).toEqual(data2);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
