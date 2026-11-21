import { hasNotice, noticeKey, staleKeys, type LicenseManifest, type LicensePackage, type NoticeEntry, type NoticeStore } from "./manifest.ts";


const ADDITIONAL = /(^|[^A-Z])(L|A)?GPL|MPL|EPL|CDDL|\bWITH\b/;
/** Operating-system packages whose license the SBOM could not reduce to one expression are composite (several licenses, exceptions) and need review too. */
const needsReview = (p: LicensePackage) => (p.license ? ADDITIONAL.test(p.license) : p.kind === "Debian package");
const line = (p: LicensePackage) => `${p.name} ${p.version ?? "(version not pinned)"} | ${p.licenseName ?? (p.mainLicense ? `multiple licenses, main: ${p.mainLicense.name}` : "license not determined")} | ${p.kind}${p.scope ? `, ${p.scope}` : ""}`;

/** The THIRD-PARTY-NOTICES text: coverage by status, components without verified full text, components with obligations beyond the text, then every full text once with the packages it applies to. */
export function renderNotices(m: LicenseManifest, store: NoticeStore | null): string {
  const covered = m.packages.filter((p) => hasNotice(store, p));
  const metadataOnly = m.packages.filter((p) => p.noticeStatus === "VERIFIED_METADATA_ONLY");
  const unresolved = m.packages.filter((p) => p.noticeStatus === "UNRESOLVED");
  const missing = [...metadataOnly, ...unresolved];
  const noAttribution = covered.filter((p) => { const c = store!.packages[noticeKey(p)].check; return c?.noticeRequired?.length && c.attribution === false; });
  const attributed = m.packages.filter((p) => store?.packages[noticeKey(p)]?.check?.attribution === true);
  const standardOnly = covered.filter((p) => store!.packages[noticeKey(p)].basis === "standard-text-only");
  const stale = staleKeys(m.packages, store);
  const out: string[] = [
    "THIRD-PARTY NOTICES - ODOS",
    "",
    `Generated at build time from sbom.spdx.json${m.spdxVersion ? ` (${m.spdxVersion}${m.created ? `, created ${m.created.slice(0, 10)}` : ""})` : ""} and the verified notice store (frontend/notices/notices.json).`,
    "The license and notice files below are reproduced exactly as found in the source named for each component (package contents, a checksum-verified source archive, an upstream release tag, or a Debian copyright file and the license texts it refers to).",
    "Only components with the status VERIFIED_FULL_TEXT have their texts below. A license identifier, a URL or a repository reference is never counted as a notice.",
    "This file is not legal advice and does not by itself establish compliance with any license. License identifiers come from package metadata and have not been independently audited.",
    "",
    `Coverage: ${covered.length} of ${m.packages.length} components have verified full text; ${metadataOnly.length} have verified metadata only; ${unresolved.length} are unresolved.${stale.length ? ` ${stale.length} stored entries no longer match the SBOM and are not used (the notice store is out of date).` : ""}`,
    `Copyright attribution: ${attributed.length} of ${m.packages.length} components have a copyright notice in a package-specific file. This is counted separately; a standard license text never counts as attribution.`,
    "",
    `== Components without verified full text (${missing.length}) ==`,
    "Their license and copyright notices still have to be obtained from the upstream sources.",
    ...missing.map((p) => {
      const e = store?.packages[noticeKey(p)];
      const other = Object.keys(store?.packages ?? {}).filter((k) => k.startsWith(`${p.kind}|${p.name}|`) && k !== noticeKey(p)).map((k) => k.split("|")[2]);
      return `- ${line(p)} | ${p.noticeStatus}${e?.reasons?.length ? ` | ${e.reasons.join("; ")}` : ""}${other.length ? ` | notice store has only version ${other.join(", ")}` : ""}`;
    }),
    "",
  ];
  const extra = m.packages.filter(needsReview);
  out.push(
    `== Components whose license has obligations beyond providing its text (${extra.length}) ==`,
    "Copyleft licenses (LGPL, GPL, MPL), license exceptions and composite operating-system licenses can require source access, relinking or other steps that this file does not address. They need separate review.",
    ...extra.map((p) => `- ${line(p)}${hasNotice(store, p) ? "" : " | no verified full text"}`),
    "",
    `== Components whose notice is a standard license text only (${standardOnly.length}) ==`,
    "No package-specific notice exists for these components: the declared license (from the distribution's package metadata) is shown with its authoritative standard text. Their copyright holders are not evidenced here.",
    ...standardOnly.map((p) => `- ${line(p)}`),
    "",
    `== Components with a license text but no copyright line in the stored files (${noAttribution.length}) ==`,
    "The full license text is stored, but none of the stored files names a copyright holder; attribution has to be taken from the upstream project.",
    ...noAttribution.map((p) => `- ${line(p)}`),
    "",
    "== License and notice texts ==",
  );
  const groups = new Map<string, { entry: NoticeEntry; pkgs: LicensePackage[] }>();
  for (const p of covered) {
    const entry = store!.packages[noticeKey(p)];
    const sig = entry.files.map((f) => `${f.name}:${f.hash}`).join("|");
    (groups.get(sig) ?? groups.set(sig, { entry, pkgs: [] }).get(sig)!).pkgs.push(p);
  }
  for (const { entry, pkgs } of [...groups.values()].sort((a, b) => a.pkgs[0].name.localeCompare(b.pkgs[0].name))) {
    out.push("", "-".repeat(78), "Applies to:", ...pkgs.map((p) => `  ${line(p)}${store!.packages[noticeKey(p)].evidenceVersion ? ` (text taken from version ${store!.packages[noticeKey(p)].evidenceVersion})` : ""}\n    source: ${store!.packages[noticeKey(p)].evidence}`));
    for (const f of entry.files) out.push("", f.role === "standard-license-text" ? `[${f.name}] (standard license text, not package-specific)` : `[${f.name}]`, store!.texts[f.hash]);
  }
  return out.join("\n") + "\n";
}
