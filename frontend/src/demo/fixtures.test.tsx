import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StructureTree } from "../components/StructureTree";
import { el, modelOf } from "../testing";
import { isPdf, matchDocument, resolveUpload, sha256Hex, type DemoDocument } from "./fixtures";

const doc = (id: string, pdfSha256: string) => ({ id, title: id === "mbo" ? "Musterbauordnung (MBO)" : "EU Regulation", pdfSha256 } as DemoDocument);
const bytes = (s: string) => new TextEncoder().encode(s).buffer as ArrayBuffer;

describe("document selection and matching", () => {
  it("matches a PDF only by its exact SHA-256", async () => {
    const sha = await sha256Hex(bytes("%PDF-1.7 demo"));
    expect(sha).toMatch(/^[0-9a-f]{64}$/);
    const docs = [doc("eu", "0".repeat(64)), doc("mbo", sha.toUpperCase())];
    expect(matchDocument(docs, sha)?.id).toBe("mbo");
    expect(matchDocument(docs, await sha256Hex(bytes("%PDF-1.7 other")))).toBeNull();
    expect(matchDocument([], sha)).toBeNull();
  });
  it("recognises PDFs by their header", () => {
    expect(isPdf(bytes("%PDF-1.4\n"))).toBe(true);
    expect(isPdf(bytes("<html>"))).toBe(false);
    expect(isPdf(new ArrayBuffer(0))).toBe(false);
  });
  it("accepts a prepared PDF", async () => {
    const data = bytes("%PDF-1.7 prepared");
    const docs = [doc("eu", "0".repeat(64)), doc("mbo", await sha256Hex(data))];
    expect((await resolveUpload(data, "mbo.pdf", docs)).id).toBe("mbo");
  });
});

describe("unsupported PDF behaviour", () => {
  const docs = [doc("eu", "0".repeat(64)), doc("mbo", "1".repeat(64))];
  it("refuses a file that is not a PDF", async () => {
    await expect(resolveUpload(bytes("<html>"), "page.pdf", docs)).rejects.toThrow("“page.pdf” is not a PDF file.");
  });
  it("explains that any other PDF is not processed and names the prepared documents", async () => {
    const err = await resolveUpload(bytes("%PDF-1.7 unknown"), "other.pdf", docs).catch((e: Error) => e);
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toContain("“other.pdf” is not one of the prepared demonstration documents");
    expect((err as Error).message).toContain("does not process PDFs");
    expect((err as Error).message).toContain("EU Regulation and Musterbauordnung (MBO)");
  });
  it("says so when the build has no prepared documents", async () => {
    await expect(resolveUpload(bytes("%PDF-1.7 x"), "x.pdf", [])).rejects.toThrow("no prepared demonstration documents");
  });
});

describe("StructureTree", () => {
  const model = modelOf([
    el("doc", "document", null, ["doc/par-6"], { region: "document" }),
    el("doc/par-6", "paragraph", "doc", ["doc/par-6/abs-1"], { marker: "§ 6", title: "Abstandsflächen", pages: [9], uncertain: true }),
    el("doc/par-6/abs-1", "absatz", "doc/par-6", [], { marker: "(1)", original_text: "(1) Beispieltext", pages: [9, 10] }),
  ]);
  const render = (selectedId: string | null = null) =>
    renderToStaticMarkup(<StructureTree model={model} selectedId={selectedId} onSelect={() => {}} />);

  it("shows the hierarchy with kinds, labels and source pages", () => {
    const html = render();
    expect(html).toContain("Abstandsflächen");
    expect(html).toContain("§ 6");
    expect(html).toContain("p.9");
    expect(html).toContain("Expand all");
    expect(html).toContain("Search text…");
  });
  it("marks the selected row", () => {
    const html = render("doc/par-6/abs-1");
    expect(html).toMatch(/node selected/);
  });
  it("shows no uncertainty or warning badges", () => {
    const html = render();
    expect(html).not.toContain("badge");
    expect(html).not.toContain("flagged only");
  });
});
