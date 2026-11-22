import { existsSync, readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import manifestFromSbom from "virtual:legal-notices";
import LegalNotices, { MULTIPLE, UNDETERMINED, filterPackages } from "./LegalNotices";
import { UNAVAILABLE, buildManifest, type NoticeStore } from "./manifest";
import { LICENSE_NAME, LICENSE_URL, REPO_URL } from "./links";
import { renderNotices } from "./notices";

const sbom = {
  spdxVersion: "SPDX-2.3",
  creationInfo: { created: "2026-11-21T10:00:00Z" },
  packages: [
    { SPDXID: "SPDXRef-root", name: "odos-backend", versionInfo: "0.1.0", licenseDeclared: "MIT" },
    { SPDXID: "SPDXRef-a", name: "react", versionInfo: "19.3.1", homepage: "NOASSERTION", licenseDeclared: "MIT", externalRefs: [{ referenceType: "purl", referenceLocator: "pkg:npm/react@19.3.1" }] },
    { SPDXID: "SPDXRef-b", name: "fastapi", versionInfo: "0.162.0", homepage: "https://github.com/fastapi/fastapi", licenseDeclared: "MIT", externalRefs: [{ referenceType: "purl", referenceLocator: "pkg:pypi/fastapi@0.162.0" }] },
    { SPDXID: "SPDXRef-c", name: "libgl1", versionInfo: "NOASSERTION", licenseDeclared: "NOASSERTION", licenseComments: "mixed licenses", externalRefs: [{ referenceType: "purl", referenceLocator: "pkg:deb/debian/libgl1" }] },
    { SPDXID: "SPDXRef-d", name: "react", versionInfo: "19.3.1", licenseDeclared: "MIT", externalRefs: [{ referenceType: "purl", referenceLocator: "pkg:npm/react@19.3.1" }] },
  ],
  relationships: [{ spdxElementId: "SPDXRef-DOCUMENT", relationshipType: "DESCRIBES", relatedSpdxElement: "SPDXRef-root" }],
};

describe("buildManifest", () => {
  const m = buildManifest(sbom);
  it("leaves out the project itself and merges duplicates", () => {
    expect(m.packages.map((p) => p.name)).toEqual(["fastapi", "libgl1", "react"]);
  });
  it("keeps declared licenses and treats NOASSERTION as not determined", () => {
    expect(m.packages.find((p) => p.name === "react")!.license).toBe("MIT");
    const lib = m.packages.find((p) => p.name === "libgl1")!;
    expect(lib).toMatchObject({ license: null, version: null, note: "mixed licenses", kind: "Debian package", url: null });
  });
  it("links the SBOM's homepage, else the registry page, never an invented URL", () => {
    expect(m.packages.find((p) => p.name === "fastapi")!.url).toBe("https://github.com/fastapi/fastapi");
    expect(m.packages.find((p) => p.name === "react")!.url).toBe("https://www.npmjs.com/package/react/v/19.3.1");
  });
  it("carries only what the page shows", () => {
    expect(Object.keys(m).sort()).toEqual(["available", "created", "packages", "spdxVersion", "staleNotices"]);
    expect(JSON.stringify(m)).not.toMatch(/\/Users\/|SPDXRef|checksum/);
  });
});

describe("filterPackages", () => {
  const { packages } = buildManifest(sbom);
  it("searches names and licenses, case-insensitively", () => {
    expect(filterPackages(packages, "FAST", "").map((p) => p.name)).toEqual(["fastapi"]);
    expect(filterPackages(packages, "mit", "")).toHaveLength(2);
  });
  it("filters by license, including the undetermined ones", () => {
    expect(filterPackages(packages, "", UNDETERMINED).map((p) => p.name)).toEqual(["libgl1"]);
    expect(filterPackages(packages, "", "MIT")).toHaveLength(2);
  });
});

describe("Legal Notices page", () => {
  it("shows the project facts, the third-party list and unknown licenses honestly", () => {
    const html = renderToStaticMarkup(<LegalNotices manifest={buildManifest(sbom)} />);
    for (const h of ["About ODOS", "Copyright and license", "Third-party open-source software"]) expect(html).toContain(h);
    expect(html).toContain("ODOS is built on 3 open-source packages and base images");
    expect(html).toContain(UNDETERMINED);
    expect(html).toContain("© 2026 AMOS Project");
    expect(html).toContain("non-commercial academic project");
    expect(html).toContain("developed in the context of the AMOS course. It is not a production service, and its results are not legal advice.");
    expect(html).not.toContain("Friedrich-Alexander");
    expect(html).toContain(`href="${REPO_URL}"`);
    expect(html).toContain(`href="${LICENSE_URL}"`);
    expect(html).toContain('href="./THIRD-PARTY-NOTICES.txt"');
    expect(html).not.toMatch(/SPDX|sbom\.spdx|Metadata only|VERIFIED_/); // no internal wording
  });
  it("says so when no SBOM was available at build time", () => {
    const html = renderToStaticMarkup(<LegalNotices manifest={UNAVAILABLE} />);
    expect(html).toContain("not available in this build");
    expect(html).not.toContain("<table");
  });
  it("is built from the repository SBOM and the notice store", () => {
    const file = new URL("../../../sbom.spdx.json", import.meta.url);
    if (!existsSync(file)) return expect(manifestFromSbom.available).toBe(false);
    const store = JSON.parse(readFileSync(new URL("../../notices/notices.json", import.meta.url), "utf8"));
    expect(manifestFromSbom).toEqual(buildManifest(JSON.parse(readFileSync(file, "utf8")), store));
    expect(manifestFromSbom.packages.length).toBeGreaterThan(100);
  });
});

describe("composite components and extracted licenses", () => {
  const composite = {
    ...sbom,
    hasExtractedLicensingInfos: [{ licenseId: "LicenseRef-X", name: "GPL-2.0 with exceptions" }],
    packages: [...sbom.packages,
      { SPDXID: "SPDXRef-img", name: "postgres", versionInfo: "17-alpine", licenseDeclared: "NOASSERTION", externalRefs: [{ referenceType: "purl", referenceLocator: "pkg:docker/postgres@17-alpine" }, { referenceCategory: "OTHER", referenceType: "main-license", referenceLocator: "https://www.postgresql.org/about/licence/", comment: "PostgreSQL License" }] },
      { SPDXID: "SPDXRef-font", name: "fonts", versionInfo: "NOASSERTION", licenseDeclared: "LicenseRef-X", externalRefs: [{ referenceType: "purl", referenceLocator: "pkg:deb/debian/fonts" }] }],
  };
  const m = buildManifest(composite);
  it("reads the main license of a composite component, never as its license", () => {
    const img = m.packages.find((p) => p.name === "postgres")!;
    expect(img.license).toBeNull();
    expect(img.mainLicense).toEqual({ name: "PostgreSQL License", url: "https://www.postgresql.org/about/licence/" });
  });
  it("shows an extracted license by its name but keeps the declared expression", () => {
    const f = m.packages.find((p) => p.name === "fonts")!;
    expect(f.license).toBe("LicenseRef-X");
    expect(f.licenseName).toBe("GPL-2.0 with exceptions");
  });
  it("filters composite components under their own heading and explains it on the page", () => {
    expect(filterPackages(m.packages, "", MULTIPLE).map((p) => p.name)).toEqual(["postgres"]);
    const html = renderToStaticMarkup(<LegalNotices manifest={m} />);
    expect(html).toContain("Multiple licenses");
    expect(html).toContain("Main software: ");
    expect(html).toContain("not of the whole image");
  });
  it("describes it in the notices file", () => {
    expect(renderNotices(m, null)).toContain("postgres 17-alpine | multiple licenses, main: PostgreSQL License | Docker image");
  });
});

describe("project license", () => {
  const license = readFileSync(new URL("../../../LICENSE", import.meta.url), "utf8");
  it("is the license in the repository's LICENSE file", () => {
    expect(license.split("\n")[0]).toBe(LICENSE_NAME); // the first line of LICENSE names the license
    expect(LICENSE_URL).toBe(`${REPO_URL}/blob/HEAD/LICENSE`);
  });
});

const MIT = "MIT License\n\nCopyright (c) 2020 Example Authors\n\nPermission is hereby granted...";
const store: NoticeStore = {
  texts: { aaaa: MIT, bbbb: "GNU LESSER GENERAL PUBLIC LICENSE ..." },
  packages: {
    "npm|react|19.3.1": { files: [{ name: "LICENSE", hash: "aaaa" }], evidence: "npm package contents" },
    "Python|fastapi|0.1.0": { files: [{ name: "LICENSE", hash: "aaaa" }], evidence: "Python distribution metadata" }, // an outdated version
    "npm|removed|1.0.0": { files: [{ name: "LICENSE", hash: "aaaa" }], evidence: "npm package contents" }, // no longer in the SBOM
  },
};

describe("third-party notices", () => {
  const m = buildManifest(sbom, store);
  it("covers a component only when the store has exactly its name and version", () => {
    expect(m.packages.map((p) => [p.name, p.notice])).toEqual([["fastapi", false], ["libgl1", false], ["react", true]]);
    expect(m.staleNotices).toBe(2); // the outdated fastapi entry and the removed package
  });
  it("without a store nothing is covered", () => {
    expect(buildManifest(sbom).packages.every((p) => !p.notice)).toBe(true);
  });
  it("reproduces the stored text exactly and names who it applies to", () => {
    const text = renderNotices(m, store);
    expect(text).toContain(MIT);
    expect(text).toContain("Coverage: 1 of 3 components have verified full text; 0 have verified metadata only; 2 are unresolved. 2 stored entries no longer match");
    expect(text).toContain("react 19.3.1 | MIT | npm");
  });
  it("lists uncovered components, with the outdated version, and never uses stale text for them", () => {
    const text = renderNotices(m, store);
    expect(text).toMatch(/- fastapi 0\.162\.0 \| MIT \| Python \| UNRESOLVED \| notice store has only version 0\.1\.0/);
    expect(text).toContain("- libgl1 (version not pinned) | license not determined | Debian package");
    expect(text.indexOf("Example Authors")).toBe(text.lastIndexOf("Example Authors")); // the removed package's entry adds no second copy
    expect(text).not.toContain("removed");
  });
  it("flags copyleft licenses and exceptions as needing more than the text", () => {
    const withLgpl = buildManifest({ ...sbom, packages: [...sbom.packages, { SPDXID: "SPDXRef-e", name: "psycopg", versionInfo: "3.3.4", licenseDeclared: "LGPL-3.0-only", externalRefs: [{ referenceType: "purl", referenceLocator: "pkg:pypi/psycopg@3.3.4" }] }] }, store);
    expect(renderNotices(withLgpl, store)).toMatch(/obligations beyond providing its text \(2\)[\s\S]*- psycopg 3\.3\.4 \| LGPL-3\.0-only/);
  });
  it("names the source of every text and flags composite operating-system licenses for review", () => {
    const deb = { ...sbom, packages: [...sbom.packages, { SPDXID: "SPDXRef-f", name: "fonts-liberation", versionInfo: "NOASSERTION", licenseDeclared: "NOASSERTION", externalRefs: [{ referenceType: "purl", referenceLocator: "pkg:deb/debian/fonts-liberation" }] }] };
    const s: NoticeStore = { texts: { ...store.texts, cccc: "GNU GENERAL PUBLIC LICENSE Version 2" }, packages: { ...store.packages, "Debian package|fonts-liberation|": { files: [{ name: "copyright", hash: "aaaa" }, { name: "common-licenses/GPL-2", hash: "cccc" }], evidence: "Debian package copyright file", evidenceVersion: "1:1.07.4-11" } } };
    const text = renderNotices(buildManifest(deb, s), s);
    expect(text).toContain("source: Debian package copyright file");
    expect(text).toContain("(text taken from version 1:1.07.4-11)");
    expect(text).toMatch(/obligations beyond providing its text \(2\)[\s\S]*- fonts-liberation \(version not pinned\) \| license not determined \| Debian package/);
    expect(text).toContain("[common-licenses/GPL-2]");
  });
  it("counts only VERIFIED_FULL_TEXT: metadata-only and unresolved entries are not notices", () => {
    const s: NoticeStore = {
      texts: { aaaa: MIT },
      packages: {
        "npm|react|19.3.1": { status: "VERIFIED_FULL_TEXT", files: [{ name: "LICENSE", hash: "aaaa" }], evidence: "npm package contents" },
        "Python|fastapi|0.162.0": { status: "VERIFIED_METADATA_ONLY", files: [], evidence: "apk metadata", metadata: { license: "MIT" }, reasons: ["the source archive contains no license file"] },
        "Debian package|libgl1|": { status: "UNRESOLVED", files: [], evidence: "none", reasons: ["no source holds license files"] },
      },
    };
    const m2 = buildManifest(sbom, s);
    expect(m2.packages.map((p) => [p.name, p.noticeStatus, p.notice])).toEqual([["fastapi", "VERIFIED_METADATA_ONLY", false], ["libgl1", "UNRESOLVED", false], ["react", "VERIFIED_FULL_TEXT", true]]);
    const text = renderNotices(m2, s);
    expect(text).toContain("Coverage: 1 of 3 components have verified full text; 1 have verified metadata only; 1 are unresolved.");
    expect(text).toMatch(/- fastapi 0\.162\.0 \| MIT \| Python \| VERIFIED_METADATA_ONLY \| the source archive contains no license file/);
    expect(text).toMatch(/- libgl1 \(version not pinned\) \| license not determined \| Debian package \| UNRESOLVED \| no source holds license files/);
  });
  it("treats entries of an older store, which have no status, as full text", () => {
    expect(buildManifest(sbom, store).packages.find((p) => p.name === "react")!.noticeStatus).toBe("VERIFIED_FULL_TEXT");
  });
  it("lists full-text components whose stored files name no copyright holder", () => {
    const s: NoticeStore = { texts: { aaaa: "Permission is hereby granted..." }, packages: { "npm|react|19.3.1": { status: "VERIFIED_FULL_TEXT", files: [{ name: "LICENSE", hash: "aaaa" }], evidence: "npm package contents", check: { noticeRequired: ["MIT"], attribution: false } } } };
    expect(renderNotices(buildManifest(sbom, s), s)).toMatch(/no copyright line in the stored files \(1\)[\s\S]*- react 19\.3\.1/);
  });
  it("labels standard texts, counts attribution separately and lists standard-text-only components", () => {
    const s: NoticeStore = {
      texts: { aaaa: "Copyright (c) 2020 Example Authors\nPermission is hereby granted...", bbbb: "MIT License\n\nCopyright (c) <year> <copyright holders>\n\nPermission is hereby granted..." },
      packages: {
        "npm|react|19.3.1": { status: "VERIFIED_FULL_TEXT", basis: "package-notice", files: [{ name: "LICENSE", hash: "aaaa" }], evidence: "npm package contents", check: { noticeRequired: ["MIT"], attribution: true } },
        "Python|fastapi|0.162.0": { status: "VERIFIED_FULL_TEXT", basis: "standard-text-only", files: [{ name: "MIT", hash: "bbbb", role: "standard-license-text" }], evidence: "APKBUILD license", check: { noticeRequired: ["MIT"], attribution: false } },
      },
    };
    const text = renderNotices(buildManifest(sbom, s), s);
    expect(text).toContain("Copyright attribution: 1 of 3 components have a copyright notice in a package-specific file.");
    expect(text).toMatch(/standard license text only \(1\) ==[\s\S]*- fastapi 0\.162\.0/);
    expect(text).toContain("[MIT] (standard license text, not package-specific)");
    expect(text).toContain("[LICENSE]\nCopyright (c) 2020 Example Authors");
  });
});
