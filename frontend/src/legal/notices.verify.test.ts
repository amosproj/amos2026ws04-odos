import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { verify } from "../../scripts/verify-notices.mjs";

const at = (p: string) => fileURLToPath(new URL(`../../${p}`, import.meta.url));

describe("committed notice store", () => {
  it("is consistent with the canonical SBOM and the provenance register", () => {
    const { failures, metrics } = verify();
    expect(failures).toEqual([]);
    expect(metrics.ordinaryFullText).toBe(metrics.ordinary); // every ordinary component has verified full text
    expect(metrics.unresolved).toBeLessThanOrEqual(3); // only the composite base images
  });

  it("notices a store that no longer matches its SBOM or its hashes", () => {
    const store = JSON.parse(readFileSync(at("notices/notices.json"), "utf8"));
    const first = Object.keys(store.texts)[0];
    store.texts[first] += " tampered";
    delete store.packages[Object.keys(store.packages)[0]];
    store.packages["npm|not-in-the-sbom|1.0.0"] = { status: "VERIFIED_FULL_TEXT", files: [], evidence: "x" };
    const dir = mkdtempSync(join(tmpdir(), "odos-notices-"));
    const p = join(dir, "notices.json");
    writeFileSync(p, JSON.stringify(store));
    const { failures } = verify({ storePath: p });
    expect(failures.some((f) => f.includes("does not hash to its key"))).toBe(true);
    expect(failures.some((f) => f.startsWith("no store entry for"))).toBe(true);
    expect(failures.some((f) => f.includes("stale store entry npm|not-in-the-sbom|1.0.0"))).toBe(true);
  });
});
