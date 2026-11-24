import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { checkSbom } from "../../scripts/check-sbom.mjs";
import { buildManifest } from "./manifest";

const sbomPath = fileURLToPath(new URL("../../../sbom.spdx.json", import.meta.url));

describe("sbom.spdx.json", () => {
  it("agrees with the lockfiles, the Dockerfiles and the compose file", () => {
    const { failures } = checkSbom({ sbomPath });
    expect(failures).toEqual([]); // a changed lockfile without a matching SBOM change fails here (and so in CI)
  });

  it("is exactly what the Legal Notices page lists", () => {
    const { counts } = checkSbom({ sbomPath });
    const m = buildManifest(JSON.parse(readFileSync(sbomPath, "utf8")));
    expect(m.packages.length).toBe(counts.components); // every component but the two project roots, no duplicates
    expect(m.packages.length).toBe(counts.byEcosystem.npm + counts.byEcosystem.pypi + counts.byEcosystem.docker + counts.byEcosystem.deb);
  });
});
