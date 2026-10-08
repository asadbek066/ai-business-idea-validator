import { describe, expect, it } from "vitest";
import { evaluateAudit } from "../scripts/audit-gate.mjs";

const adv = (name, ghsa, severity) => ({
  name,
  severity,
  title: `${name} issue`,
  url: `https://github.com/advisories/${ghsa}`,
});
const BRACES = "GHSA-vfj7-8cjw-p6xm";
const entry = (over = {}) => ({ id: BRACES, package: "braces", reason: "no fix", expires: "2026-11-08", ...over });
const NOW = new Date("2026-10-08T00:00:00Z");

const report = (vulns) => ({ vulnerabilities: vulns });
const bracesReport = report({
  braces: { severity: "high", via: [adv("braces", BRACES, "high")] },
  micromatch: { severity: "high", via: ["braces"] },
});

describe("audit gate decision logic", () => {
  it("passes an allowlisted advisory, including packages flagged only transitively", () => {
    const r = evaluateAudit(bracesReport, [entry()], NOW);
    expect(r.ok).toBe(true);
    expect(r.allowed.map((a) => a.id)).toEqual([BRACES]);
  });

  it("fails an unlisted high advisory", () => {
    const r = evaluateAudit(bracesReport, [], NOW);
    expect(r.ok).toBe(false);
    expect(r.failed).toHaveLength(1);
  });

  it("fails a critical advisory", () => {
    const r = evaluateAudit(report({ next: { via: [adv("next", "GHSA-aaaa-bbbb-cccc", "critical")] } }), [], NOW);
    expect(r.ok).toBe(false);
  });

  it("fails when the allowlist entry has expired", () => {
    const r = evaluateAudit(bracesReport, [entry({ expires: "2026-10-01" })], NOW);
    expect(r.ok).toBe(false);
    expect(r.expired).toHaveLength(1);
  });

  it("fails on a stale entry that matches no current advisory", () => {
    const r = evaluateAudit(report({}), [entry()], NOW);
    expect(r.ok).toBe(false);
    expect(r.stale).toHaveLength(1);
  });

  it("ignores moderate advisories", () => {
    const r = evaluateAudit(report({ esbuild: { via: [adv("esbuild", "GHSA-67mh-4wv8-2f99", "moderate")] } }), [], NOW);
    expect(r.ok).toBe(true);
  });

  it("fails when a package has one allowlisted and one non-allowlisted advisory", () => {
    const r = evaluateAudit(
      report({ braces: { severity: "high", via: [adv("braces", BRACES, "high"), adv("braces", "GHSA-zzzz-yyyy-xxxx", "high")] } }),
      [entry()],
      NOW,
    );
    expect(r.ok).toBe(false);
    expect(r.allowed).toHaveLength(1);
    expect(r.failed.map((a) => a.id)).toEqual(["GHSA-zzzz-yyyy-xxxx"]);
  });

  it("rejects malformed allowlist entries", () => {
    const r = evaluateAudit(bracesReport, [entry({ reason: "" })], NOW);
    expect(r.ok).toBe(false);
    expect(r.errors).toHaveLength(1);
  });

  it("fails a high advisory that has no GHSA url instead of ignoring it", () => {
    const r = evaluateAudit(
      report({ leftpad: { severity: "high", via: [{ name: "leftpad", severity: "high", title: "x", source: 4242, url: "https://example.test/advisory/1" }] } }),
      [],
      NOW,
    );
    expect(r.ok).toBe(false);
    expect(r.failed.map((a) => a.id)).toEqual(["unidentified:4242"]);
  });

  it("fails closed when a blocking package cannot be traced to any advisory", () => {
    const r = evaluateAudit(report({ orphan: { severity: "critical", via: ["missing-parent"] } }), [], NOW);
    expect(r.ok).toBe(false);
    expect(r.errors.join(" ")).toContain("orphan");
  });
});
