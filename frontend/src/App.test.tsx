// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import manifest from "virtual:legal-notices";
import App from "./App";
import { COPYRIGHT, LICENSE_URL } from "./legal/links";
import { filterPackages } from "./legal/LegalNotices";
import type { LicensePackage } from "./legal/manifest";

// the workspace itself is tested elsewhere; here it is a stand-in, so the test is about routing and the footer
vi.mock("./demo/DemoApp", () => ({ default: () => <main data-testid="workspace">workspace</main> }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
const show = async (hash: string) => {
  window.location.hash = hash;
  await act(async () => { root.render(<App />); });
  await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
};
const set = (el: HTMLInputElement | HTMLSelectElement, value: string) => {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
  el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
};

beforeEach(() => { window.scrollTo = vi.fn(() => Promise.resolve()) as unknown as typeof window.scrollTo; // some browsers return a value from scrollTo
  host = document.createElement("div"); document.body.append(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); window.location.hash = ""; });

describe("footer and routing", () => {
  it("shows exactly one footer, under the workspace and under the Legal Notices page", async () => {
    for (const hash of ["", "#/legal"]) {
      await show(hash);
      expect(host.querySelectorAll("footer")).toHaveLength(1);
      expect(host.querySelector("footer")!.textContent).toContain(COPYRIGHT);
      expect(host.querySelector("footer")!.textContent).toContain("Non-commercial academic project (AMOS course)");
      expect(host.querySelector("footer")!.textContent).not.toContain("FAU");
    }
  });
  it("the footer links the actual license and the Legal Notices page", async () => {
    await show("");
    const links = [...host.querySelectorAll("footer a")].map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links).toEqual([["MIT License", LICENSE_URL], ["Legal Notices", "#/legal"]]);
  });
  it("#/legal shows the Legal Notices page, any other hash the workspace (which stays mounted)", async () => {
    await show("#/legal");
    expect(host.querySelector("h1")!.textContent).toBe("Legal Notices");
    expect(host.querySelector<HTMLElement>("[data-testid=workspace]")!.closest<HTMLElement>(".app-page")!.hidden).toBe(true);
    await show("#library");
    expect(host.querySelector("h1")).toBeNull();
    expect(host.querySelector<HTMLElement>("[data-testid=workspace]")!.closest<HTMLElement>(".app-page")!.hidden).toBe(false);
  });
});

describe("Legal Notices page against the real SBOM", () => {
  const rows = () => [...host.querySelectorAll(".legal-table tbody tr")];
  const directPkgs = manifest.packages.filter((p: LicensePackage) => p.direct);
  /** Click the "All Dependencies" toggle button so all 257 rows are visible. */
  const showAll = async () => {
    const btn = [...host.querySelectorAll<HTMLButtonElement>(".legal-view-toggle button")].find((b) => b.textContent?.startsWith("All"));
    if (btn) await act(async () => btn.click());
  };

  it("shows Direct Dependencies by default, then all when switching to All view", async () => {
    await show("#/legal");
    expect(rows()).toHaveLength(directPkgs.length);
    expect(rows().length).toBeGreaterThan(0);
    await showAll();
    expect(rows()).toHaveLength(manifest.packages.length);
  });
  it("direct view shows only packages flagged direct in the manifest", async () => {
    await show("#/legal");
    expect(rows().map((r) => r.querySelector("th")!.textContent).sort())
      .toEqual(directPkgs.map((p: LicensePackage) => p.name).sort());
  });
  it("lists every third-party component of the SBOM in the All view, with its own name and version", async () => {
    await show("#/legal");
    await showAll();
    expect(rows()).toHaveLength(manifest.packages.length);
    expect(rows().map((r) => r.querySelector("th")!.textContent + "@" + r.children[1].textContent).sort())
      .toEqual(manifest.packages.map((p: LicensePackage) => `${p.name}@${p.version ?? "Not pinned"}`).sort());
  });
  it("searches by name and filters by license in the All view", async () => {
    await show("#/legal");
    await showAll();
    await act(async () => set(host.querySelector<HTMLInputElement>("input[type=search]")!, "react"));
    expect(rows()).toHaveLength(filterPackages(manifest.packages, "react", "").length);
    expect(rows().length).toBeGreaterThan(0);
    expect(rows().length).toBeLessThan(manifest.packages.length);
    await act(async () => set(host.querySelector<HTMLInputElement>("input[type=search]")!, ""));
    await act(async () => set(host.querySelector<HTMLSelectElement>("select")!, "MIT"));
    expect(rows()).toHaveLength(manifest.packages.filter((p: LicensePackage) => p.license === "MIT").length);
    expect(rows().every((r) => r.children[2].textContent === "MIT")).toBe(true);
  });
  it("docker and debian packages have source links in the All view", async () => {
    await show("#/legal");
    await showAll();
    const row = (name: string) => rows().find((r) => r.querySelector("th")!.textContent === name)!;
    const srcLink = (name: string) => row(name).children[4].querySelector("a");
    expect(srcLink("node")!.getAttribute("href")).toBe("https://hub.docker.com/_/node");
    expect(srcLink("node")!.textContent).toContain("Docker Hub");
    expect(srcLink("postgres")!.getAttribute("href")).toBe("https://hub.docker.com/_/postgres");
    expect(srcLink("python")!.getAttribute("href")).toBe("https://hub.docker.com/_/python");
    expect(srcLink("libgl1")!.getAttribute("href")).toBe("https://packages.debian.org/bookworm/libgl1");
    expect(srcLink("libgl1")!.textContent).toContain("Debian package");
    expect(srcLink("fonts-liberation")!.getAttribute("href")).toBe("https://packages.debian.org/bookworm/fonts-liberation");
    expect(srcLink("libglib2.0-0")!.getAttribute("href")).toBe("https://packages.debian.org/bookworm/libglib2.0-0");
  });
  it("packages without a pinned version show Not pinned with a tooltip", async () => {
    await show("#/legal");
    await showAll();
    const abbrs = [...host.querySelectorAll(".legal-table tbody td abbr")];
    expect(abbrs.length).toBeGreaterThan(0);
    expect(abbrs.every((a) => a.textContent === "Not pinned")).toBe(true);
    expect(abbrs.every((a) => a.getAttribute("title")!.includes("not pinned"))).toBe(true);
  });
  it("leaves no license undetermined: composite components name their main license with a link", async () => {
    expect(manifest.packages.filter((p: LicensePackage) => !p.licenseName && !p.mainLicense).map((p: LicensePackage) => p.name)).toEqual([]);
    await show("#/legal");
    await showAll();
    const row = (name: string) => rows().find((r) => r.querySelector("th")!.textContent === name)!;
    for (const [name, text, href] of [
      ["postgres", "PostgreSQL License", "https://www.postgresql.org/about/licence/"],
      ["python", "Python Software Foundation License", "https://docs.python.org/3/license.html"],
      ["node", "MIT License", "https://github.com/nodejs/node/blob/main/LICENSE"],
    ]) {
      const cell = row(name).children[2];
      expect(cell.textContent).toBe(`Multiple licenses · Main software: ${text}`);
      expect(cell.querySelector("a")!.getAttribute("href")).toBe(href);
    }
    expect(row("fonts-liberation").children[2].textContent).toBe("GPL-2.0 with the Liberation font exceptions");
    expect(row("libgl1").children[2].textContent).toBe("MIT");
    expect(row("libglib2.0-0").children[2].textContent).toBe("Multiple licenses · Main license: LGPL-2.1-or-later");
    await act(async () => set(host.querySelector<HTMLSelectElement>("select")!, "Multiple licenses"));
    expect(rows().map((r) => r.querySelector("th")!.textContent).sort()).toEqual(["libglib2.0-0", "node", "postgres", "python"]);
  });
});
