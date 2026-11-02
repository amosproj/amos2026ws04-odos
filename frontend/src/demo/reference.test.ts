import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// scripts/demo-reference.json is the committed list of SHA-256 hashes `npm run demo:verify` checks a setup against.
// It must agree with the PDF hashes the repository documents (backend/data/input/SOURCE.md) and hold only hashes.
const REFERENCE = resolve(__dirname, "../../scripts/demo-reference.json");
const SOURCE_MD = resolve(__dirname, "../../../backend/data/input/SOURCE.md");
const MANIFEST = resolve(__dirname, "../../public/demo/manifest.json");

type Entry = { sha256: string; canonicalSha256?: string };
type Reference = { manifest: Entry; documents: Record<string, { pdfSha256: string; files: Record<string, Entry> }> };
const reference = JSON.parse(readFileSync(REFERENCE, "utf8")) as Reference;
const SHA = /^[0-9a-f]{64}$/;

describe("demo reference hashes", () => {
  it("lists the two prepared documents with well-formed SHA-256 values", () => {
    expect(Object.keys(reference.documents).sort()).toEqual(["eu-2023-1230", "mbo"]);
    expect(reference.manifest.sha256).toMatch(SHA);
    for (const d of Object.values(reference.documents)) {
      expect(d.pdfSha256).toMatch(SHA);
      expect(Object.keys(d.files).map((f) => f.split("/").pop()!.replace(/^.*?\.(legal-view\.json|legal\.json)$/, "$1")).sort())
        .toEqual(["legal-view.json", "legal.json", "pipeline.json", "structure.json"]);
      for (const e of Object.values(d.files)) {
        expect(e.sha256).toMatch(SHA);
        expect(e.canonicalSha256).toMatch(SHA); // every fixture is JSON and also carries the float-noise-tolerant hash
      }
    }
  });

  it("uses the PDF hashes documented in backend/data/input/SOURCE.md", () => {
    const source = readFileSync(SOURCE_MD, "utf8");
    expect(source).toContain(reference.documents.mbo.pdfSha256);
    expect(source).toContain(reference.documents["eu-2023-1230"].pdfSha256);
  });

  it("contains no text, paths or secrets, only names and hashes", () => {
    expect(readFileSync(REFERENCE, "utf8")).not.toMatch(/\/Users\/|\/home\/|[A-Za-z]:\\\\|token|secret|password/i);
  });

  it.skipIf(!existsSync(MANIFEST))("matches the PDF hashes of a locally built manifest", () => {
    const manifest = JSON.parse(readFileSync(MANIFEST, "utf8")) as { documents: { id: string; pdfSha256: string }[] };
    for (const d of manifest.documents) expect(d.pdfSha256).toBe(reference.documents[d.id].pdfSha256);
  });
});
