import { describe, it, expect, vi, beforeEach } from "vitest";
import { tripwire } from "../tripwires";

describe("tripwire", () => {
  beforeEach(() => {
    tripwire.clearWarnings();
  });

  describe("checkForSemantic200Error", () => {
    it("detects response with error key", () => {
      const data = { error: "something went wrong" };
      const result = tripwire.checkForSemantic200Error(data, "/test");
      expect(result).toBe(true);
    });

    it("detects response with status=error", () => {
      const data = { status: "error", message: "fail" };
      const result = tripwire.checkForSemantic200Error(data, "/test");
      expect(result).toBe(true);
    });

    it("returns false for clean responses", () => {
      const data = { items: [1, 2], status: "ok" };
      const result = tripwire.checkForSemantic200Error(data, "/test");
      expect(result).toBe(false);
    });

    it("returns false for null/undefined", () => {
      expect(tripwire.checkForSemantic200Error(null, "/test")).toBe(false);
      expect(tripwire.checkForSemantic200Error(undefined, "/test")).toBe(false);
    });

    it("adds warning to warnings list when error detected", () => {
      tripwire.checkForSemantic200Error({ error: "bad" }, "/api/test");
      const warnings = tripwire.getWarnings();
      expect(warnings).toHaveLength(1);
      expect(warnings[0].category).toBe("semantic_200_error");
      expect(warnings[0].message).toContain("/api/test");
    });
  });

  describe("assertShape", () => {
    it("returns true when shape matches", () => {
      const data = { id: 1, name: "Alice", items: [1, 2] };
      const schema = { id: "required", name: "required", items: "array" };
      expect(tripwire.assertShape(data, schema, "test")).toBe(true);
    });

    it("returns false and warns on missing required field", () => {
      const data = { id: 1 };
      const schema = { id: "required", name: "required" };
      expect(tripwire.assertShape(data, schema, "test")).toBe(false);
      expect(tripwire.getWarnings()[0].category).toBe("missing_field");
    });

    it("returns false for null data", () => {
      expect(tripwire.assertShape(null, { id: "required" }, "test")).toBe(false);
      expect(tripwire.getWarnings()[0].category).toBe("null_response");
    });

    it("returns false when array field is not an array", () => {
      const data = { items: "not-an-array" };
      const schema = { items: "array" };
      expect(tripwire.assertShape(data, schema, "test")).toBe(false);
      expect(tripwire.getWarnings()[0].category).toBe("wrong_type");
    });

    it("returns false when number field is not a number", () => {
      const data = { count: "five" };
      const schema = { count: "number" };
      expect(tripwire.assertShape(data, schema, "test")).toBe(false);
      expect(tripwire.getWarnings()[0].category).toBe("wrong_type");
    });
  });

  describe("checkWriteConsistency", () => {
    it("warns when written item not found in list", () => {
      tripwire.checkWriteConsistency(99, [{ id: 1 }, { id: 2 }], "test");
      const warnings = tripwire.getWarnings();
      expect(warnings).toHaveLength(1);
      expect(warnings[0].category).toBe("write_inconsistency");
    });

    it("does not warn when written item is found in list", () => {
      tripwire.checkWriteConsistency(1, [{ id: 1 }, { id: 2 }], "test");
      expect(tripwire.getWarnings()).toHaveLength(0);
    });

    it("does not warn for null id or non-array list", () => {
      tripwire.checkWriteConsistency(null, [{ id: 1 }], "test");
      tripwire.checkWriteConsistency(1, "not-array", "test");
      expect(tripwire.getWarnings()).toHaveLength(0);
    });
  });

  describe("warnings management", () => {
    it("getWarnings returns a copy", () => {
      tripwire.warn("test", "msg");
      const w = tripwire.getWarnings();
      w.push({ fake: true });
      expect(tripwire.getWarnings()).toHaveLength(1);
    });

    it("clearWarnings empties the list", () => {
      tripwire.warn("test", "msg1");
      tripwire.warn("test", "msg2");
      expect(tripwire.getWarnings()).toHaveLength(2);
      tripwire.clearWarnings();
      expect(tripwire.getWarnings()).toHaveLength(0);
    });

    it("caps warnings at 100 entries", () => {
      for (let i = 0; i < 110; i++) {
        tripwire.warn("test", `msg${i}`);
      }
      expect(tripwire.getWarnings()).toHaveLength(100);
    });
  });
});
