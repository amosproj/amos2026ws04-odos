/** The lightweight license manifest the Legal Notices page shows, derived from the repository's SPDX SBOM. */
export type LicensePackage = {
  name: string;
  version: string | null;
  /** The declared SPDX license expression, or null when the SBOM does not state one (NOASSERTION). */
  license: string | null;
  /** The license as people read it: the declared expression with extracted-license ids (LicenseRef-...) replaced by their names. */
  licenseName: string | null;
  /** For a composite component (a Docker image, a package with many licenses): its main license. It does not apply to the whole component. */
  mainLicense: { name: string; url: string | null } | null;
  kind: string;
  url: string | null;
  /** The SBOM's own remark on a package whose license is not determined. */
  note: string | null;
  /** Whether the SBOM calls the component a runtime or a development dependency (null: it does not say). */
  scope: "runtime" | "development" | null;
  /** True when the package is a direct (first-level) dependency of a project root, as recorded by a DEPENDS_ON relationship in the SBOM. */
  direct: boolean;
  /** How well the notice store evidences this exact name and version; only VERIFIED_FULL_TEXT counts as a notice. */
  noticeStatus: NoticeStatus;
  /** Shorthand for noticeStatus === "VERIFIED_FULL_TEXT". */
  notice: boolean;
};

export type LicenseManifest = {
  available: boolean;
  spdxVersion: string | null;
  created: string | null;
  packages: LicensePackage[];
  /** Notice-store entries that no longer match any SBOM component. */
  staleNotices: number;
};

/**
 * VERIFIED_FULL_TEXT: the stored files hold the license text(s) the component declares (not just an identifier or a URL).
 * VERIFIED_METADATA_ONLY: a license identifier or repository reference is verified, but the full text is missing or incomplete.
 * UNRESOLVED: no evidence.
 */
export type NoticeStatus = "VERIFIED_FULL_TEXT" | "VERIFIED_METADATA_ONLY" | "UNRESOLVED";
/** Verified notice files per package. Texts are stored once by content hash, exactly as the source ships them. */
export type NoticeEntry = {
  /** Absent in stores made before statuses existed: those entries always hold full texts. */
  status?: NoticeStatus;
  /** role "standard-license-text": an authoritative standard text attached because the component's own files lack it; it carries no copyright attribution. */
  files: { name: string; hash: string; role?: "standard-license-text" }[];
  evidence: string;
  evidenceVersion?: string;
  reasons?: string[];
  notes?: string[];
  /** "standard-text-only": no package-specific notice exists, the text is a standard license text. */
  basis?: "package-notice" | "standard-text-only";
  standardTexts?: string[];
  composite?: { contains: number; fullText: number };
  metadata?: { license?: string; source?: string; branch?: string; commit?: string };
  check?: { required?: string | null; present?: string[]; missing?: string[]; unverifiable?: string[]; noticeRequired?: string[]; attribution?: boolean };
};
export type NoticeStore = { texts: Record<string, string>; packages: Record<string, NoticeEntry> };

export const noticeKey = (p: Pick<LicensePackage, "kind" | "name" | "version">) => `${p.kind}|${p.name}|${p.version ?? ""}`;

/** The evidence status for exactly this name and version (the version is empty when the SBOM pins none). */
export const noticeStatus = (store: NoticeStore | null, p: Pick<LicensePackage, "kind" | "name" | "version">): NoticeStatus => {
  const e = store?.packages[noticeKey(p)];
  return e ? e.status ?? "VERIFIED_FULL_TEXT" : "UNRESOLVED";
};
/** A component is covered only with verified full text. */
export const hasNotice = (store: NoticeStore | null, p: Pick<LicensePackage, "kind" | "name" | "version">) => noticeStatus(store, p) === "VERIFIED_FULL_TEXT";

/** Store entries that no SBOM component refers to any more (removed or version changed). They are never used. */
export function staleKeys(manifestPackages: LicensePackage[], store: NoticeStore | null): string[] {
  const current = new Set(manifestPackages.map(noticeKey));
  return Object.keys(store?.packages ?? {}).filter((k) => !current.has(k));
}

export const UNAVAILABLE: LicenseManifest = { available: false, spdxVersion: null, created: null, packages: [], staleNotices: 0 };

type SpdxPackage = {
  SPDXID?: string; comment?: string; name?: string; versionInfo?: string; homepage?: string; licenseDeclared?: string; licenseComments?: string;
  externalRefs?: { referenceType?: string; referenceLocator?: string; comment?: string }[];
};
type Spdx = { hasExtractedLicensingInfos?: { licenseId?: string; name?: string }[]; spdxVersion?: string; creationInfo?: { created?: string }; packages?: SpdxPackage[]; relationships?: { spdxElementId?: string; relationshipType?: string; relatedSpdxElement?: string }[] };

const KINDS: Record<string, string> = { pypi: "Python", npm: "npm", docker: "Docker image", deb: "Debian package" };
const known = (v: string | undefined) => (v && v !== "NOASSERTION" && v !== "NONE" ? v : null);
const web = (v: string | undefined) => (v && /^https?:\/\//.test(v) ? v : null);

/** Registry page of a package, derived from its purl; the SBOM's homepage is preferred when it has one. */
function registryUrl(type: string, name: string, version: string | null) {
  if (type === "npm") return `https://www.npmjs.com/package/${name}${version ? `/v/${version}` : ""}`;
  if (type === "pypi") return `https://pypi.org/project/${name}/${version ? `${version}/` : ""}`;
  // Official Docker Hub page for the named image (all three ODOS base images are Docker official images).
  if (type === "docker") return `https://hub.docker.com/_/${name}`;
  // Official Debian package page. ODOS backend images are bookworm-slim, so bookworm is the right suite.
  if (type === "deb") return `https://packages.debian.org/bookworm/${name}`;
  return null;
}

const mainLicenseOf = (p: SpdxPackage) => {
  const r = p.externalRefs?.find((x) => x.referenceType === "main-license");
  return r?.comment ? { name: r.comment, url: web(r.referenceLocator) } : null;
};

/** SBOM (SPDX JSON) to manifest: the described root components are the project itself, not third-party, and are left out; duplicates are merged. */
export function buildManifest(sbom: Spdx, store: NoticeStore | null = null): LicenseManifest {
  const roots = new Set((sbom.relationships ?? []).filter((r) => r.relationshipType === "DESCRIBES").map((r) => r.relatedSpdxElement));
  // Direct dependencies: packages that a root directly DEPENDS_ON (first-level only, not transitive).
  const directSPDXIDs = new Set((sbom.relationships ?? []).filter((r) => r.spdxElementId && roots.has(r.spdxElementId) && r.relationshipType === "DEPENDS_ON").map((r) => r.relatedSpdxElement));
  const seen = new Map<string, LicensePackage>();
  for (const p of sbom.packages ?? []) {
    if (!p.name || (p.SPDXID && roots.has(p.SPDXID))) continue;
    const purl = p.externalRefs?.find((r) => r.referenceType === "purl")?.referenceLocator ?? "";
    const type = /^pkg:([^/]+)\//.exec(purl)?.[1] ?? "";
    const version = known(p.versionInfo);
    const license = known(p.licenseDeclared);
    const isDirect = !!(p.SPDXID && directSPDXIDs.has(p.SPDXID));
    const key = `${KINDS[type] ?? "Other"}|${p.name}|${version}`;
    // If this SPDXID is direct, mark the entry direct even if another duplicate entry was added first.
    if (seen.has(key)) { if (isDirect) seen.get(key)!.direct = true; continue; }
    const entry: LicensePackage = {
      name: p.name, version, license, kind: KINDS[type] ?? "Other",
      licenseName: license ? license.replace(/LicenseRef-[A-Za-z0-9.-]+/g, (id) => sbom.hasExtractedLicensingInfos?.find((e) => e.licenseId === id)?.name ?? id) : null,
      mainLicense: mainLicenseOf(p),
      url: web(p.homepage) ?? registryUrl(type, p.name, version),
      note: license ? null : p.licenseComments ?? null,
      scope: /\bdevelopment dependency/.test(p.comment ?? "") ? "development" : /\bruntime dependency/.test(p.comment ?? "") ? "runtime" : null,
      direct: isDirect,
      noticeStatus: "UNRESOLVED",
      notice: false,
    };
    entry.noticeStatus = noticeStatus(store, entry);
    entry.notice = entry.noticeStatus === "VERIFIED_FULL_TEXT";
    seen.set(key, entry);
  }
  const packages = [...seen.values()].sort((a, b) => a.name.localeCompare(b.name) || (a.version ?? "").localeCompare(b.version ?? ""));
  return { available: true, spdxVersion: sbom.spdxVersion ?? null, created: sbom.creationInfo?.created ?? null, packages, staleNotices: staleKeys(packages, store).length };
}
