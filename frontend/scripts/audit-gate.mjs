#!/usr/bin/env node
/**
 * Dependency audit gate for the full tree (dev included). Fails on any
 * high/critical advisory unless it is listed in audit-allowlist.json.
 * Allowlist entries need { id (GHSA), package, reason, expires (ISO date) }.
 * Expired entries and entries matching no current advisory also fail, so
 * exceptions cannot go stale. Production-only cleanliness is enforced
 * separately with `npm audit --omit=dev` (see `npm run audit:gate`).
 * Usage: node scripts/audit-gate.mjs [--with-prod] [allowlistPath]
 *   --with-prod  first run the production-only audit (no exceptions); used by `npm run audit:gate`
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const BLOCKING = new Set(["high", "critical"]);

export function ghsaFromUrl(url) {
  const m = /GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}/i.exec(String(url ?? ""));
  return m ? m[0].toLowerCase().replace(/^ghsa/, "GHSA") : null;
}

/** Collect real advisory objects (not package-name strings) from `npm audit --json`. */
export function collectAdvisories(report) {
  const found = new Map();
  for (const [pkg, vuln] of Object.entries(report?.vulnerabilities ?? {})) {
    for (const via of vuln.via ?? []) {
      if (typeof via !== "object" || via === null) continue;
      // An advisory without a GHSA url still has to be gated: give it an id that
      // can never match the allowlist format so it fails closed if it is blocking.
      const id = ghsaFromUrl(via.url) ?? `unidentified:${via.source ?? via.url ?? pkg}`;
      const entry = found.get(id) ?? { id, package: via.name ?? pkg, severity: via.severity, title: via.title ?? "" };
      found.set(id, entry);
    }
  }
  return [...found.values()];
}

/**
 * Pure decision logic. Returns { ok, allowed, failed, expired, stale, errors }.
 * `now` is injectable for tests.
 */
export function evaluateAudit(report, allowlist, now = new Date()) {
  const errors = [];
  const entries = Array.isArray(allowlist) ? allowlist : [];
  const byId = new Map();
  for (const e of entries) {
    const missing = ["id", "package", "reason", "expires"].filter((k) => typeof e?.[k] !== "string" || !e[k].trim());
    const expiresAt = Date.parse(`${e?.expires}T23:59:59Z`);
    if (missing.length) errors.push(`allowlist entry ${JSON.stringify(e?.id ?? e)} is missing: ${missing.join(", ")}`);
    else if (Number.isNaN(expiresAt)) errors.push(`allowlist entry ${e.id} has an invalid expires date: ${e.expires}`);
    else byId.set(e.id, { ...e, expiresAt });
  }

  const advisories = collectAdvisories(report).filter((a) => BLOCKING.has(a.severity));
  const allowed = [];
  const failed = [];
  const expired = [];
  const seen = new Set();
  for (const adv of advisories) {
    const entry = byId.get(adv.id);
    if (!entry) failed.push(adv);
    else if (entry.expiresAt < now.getTime()) {
      expired.push({ ...adv, expires: entry.expires });
      seen.add(adv.id);
    } else {
      allowed.push({ ...adv, expires: entry.expires, reason: entry.reason });
      seen.add(adv.id);
    }
  }
  const stale = [...byId.values()].filter((e) => !seen.has(e.id));
  // Fail closed if npm reports a blocking package that cannot be traced to any
  // advisory object: the report shape changed and this gate no longer sees it.
  const blockingPackages = Object.entries(report?.vulnerabilities ?? {})
    .filter(([, v]) => BLOCKING.has(v?.severity))
    .map(([name]) => name);
  if (blockingPackages.length && !advisories.length) {
    errors.push(`npm reports high/critical packages (${blockingPackages.join(", ")}) but no advisory could be identified`);
  }
  const ok = !failed.length && !expired.length && !stale.length && !errors.length;
  return { ok, allowed, failed, expired, stale, errors };
}

function table(title, rows) {
  if (!rows.length) return;
  console.log(`\n${title}`);
  for (const r of rows) console.log(`  ${r.id.padEnd(22)} ${String(r.package).padEnd(20)} ${r.severity ?? ""}  ${r.detail ?? ""}`.trimEnd());
}

// When launched via `npm run`, a user-level `allow-scripts` setting is exported
// as npm_config_allow_scripts and makes nested npm calls abort (EALLOWSCRIPTS).
// An audit never runs install scripts, so drop it from the child environment.
function childEnv() {
  const env = { ...process.env };
  delete env.npm_config_allow_scripts;
  delete env["npm_config_allow-scripts"];
  return env;
}

function main() {
  const args = process.argv.slice(2);
  const withProd = args.includes("--with-prod");
  const positional = args.filter((a) => !a.startsWith("--"));
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const allowlistPath = positional[0] ?? path.join(root, "audit-allowlist.json");
  const allowlist = JSON.parse(fs.readFileSync(allowlistPath, "utf8"));

  const npm = process.platform === "win32" ? "npm.cmd" : "npm";
  if (withProd) {
    console.log("audit-gate: production dependencies (no exceptions)");
    const prod = spawnSync(npm, ["audit", "--omit=dev", "--audit-level=high"], {
      cwd: root,
      env: childEnv(),
      stdio: "inherit",
      shell: process.platform === "win32",
    });
    if (prod.status !== 0) process.exit(prod.status ?? 1);
  }
  const res = spawnSync(npm, ["audit", "--json"], {
    cwd: root,
    env: childEnv(),
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    shell: process.platform === "win32",
  });
  let report;
  try {
    report = JSON.parse(res.stdout);
  } catch {
    console.error("audit-gate: could not parse `npm audit --json` output (registry unreachable?)");
    console.error(res.stderr || res.stdout);
    process.exit(2);
  }
  if (report.error) {
    console.error(`audit-gate: npm audit failed: ${report.error.summary ?? JSON.stringify(report.error)}`);
    process.exit(2);
  }

  const r = evaluateAudit(report, allowlist);
  table("ALLOWED (allowlisted, still tracked):", r.allowed.map((a) => ({ ...a, detail: `expires ${a.expires}` })));
  table("FAILED (high/critical, not allowlisted):", r.failed.map((a) => ({ ...a, detail: a.title })));
  table("FAILED (allowlist entry expired):", r.expired.map((a) => ({ ...a, detail: `expired ${a.expires}` })));
  table("FAILED (stale allowlist entry, advisory no longer present; remove it):", r.stale.map((e) => ({ id: e.id, package: e.package, detail: `expires ${e.expires}` })));
  for (const e of r.errors) console.log(`\nFAILED (invalid allowlist): ${e}`);
  console.log(r.ok ? `\naudit-gate: OK (${r.allowed.length} allowed)` : "\naudit-gate: FAILED");
  process.exit(r.ok ? 0 : 1);
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) main();
