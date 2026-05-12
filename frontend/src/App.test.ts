import { describe, expect, it } from "vitest";
import { shouldApplyIncomingRevision } from "./App";

describe("shouldApplyIncomingRevision", () => {
  it("accepts payload without revision", () => {
    expect(shouldApplyIncomingRevision(undefined, 4)).toBe(true);
  });

  it("accepts incoming revision when store has no revision yet", () => {
    expect(shouldApplyIncomingRevision(0, -1)).toBe(true);
  });

  it("rejects stale revision", () => {
    expect(shouldApplyIncomingRevision(3, 4)).toBe(false);
  });

  it("accepts equal or newer revision", () => {
    expect(shouldApplyIncomingRevision(4, 4)).toBe(true);
    expect(shouldApplyIncomingRevision(5, 4)).toBe(true);
  });
});
