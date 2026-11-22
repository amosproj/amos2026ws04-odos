import { useEffect, useMemo, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import manifestFromSbom from "virtual:legal-notices";
import { COPYRIGHT, LICENSE_NAME, LICENSE_URL, NOTICES_URL, REPO_URL } from "./links";
import type { LicenseManifest, LicensePackage } from "./manifest";
import "./legal.css";

export const UNDETERMINED = "License not determined";
export const MULTIPLE = "Multiple licenses";
const licenseLabel = (p: LicensePackage) => p.licenseName ?? (p.mainLicense ? MULTIPLE : UNDETERMINED);

/** Packages matching a search over name and license, and an exact license (UNDETERMINED for those without one). */
export function filterPackages(packages: LicensePackage[], query: string, license: string): LicensePackage[] {
  const q = query.trim().toLowerCase();
  return packages.filter((p) => (!license || licenseLabel(p) === license) && (!q || `${p.name} ${licenseLabel(p)}`.toLowerCase().includes(q)));
}

const KIND_LABEL: Record<string, string> = { npm: "npm (frontend)", Python: "Python (backend)", "Docker image": "Docker image", "Debian package": "System package" };
const typeOf = (p: LicensePackage) => `${KIND_LABEL[p.kind] ?? p.kind}${p.scope ? ` · ${p.scope}` : ""}`;

export default function LegalNotices({ manifest = manifestFromSbom }: { manifest?: LicenseManifest }) {
  useEffect(() => { window.scrollTo(0, 0); }, []); // braces: an effect must not return scrollTo's result (React would take it for a cleanup function)
  return (
    <main className="home legal" id="top">
      <AppHeader legal />
      <div className="shell legal-body">
        <p className="eyebrow"><i aria-hidden="true" />Legal Notices</p>
        <h1 className="home-title">Legal Notices</h1>
        <section aria-labelledby="legal-about">
          <h2 id="legal-about">About ODOS</h2>
          <p>ODOS extracts the structure of German and EU legal documents. It is a non-commercial academic project, developed in the context of the AMOS course. It is not a production service, and its results are not legal advice.</p>
          <p>The source code is public: <a href={REPO_URL} target="_blank" rel="noopener noreferrer">github.com/amosproj/amos2026ws04-odos</a>.</p>
        </section>
        <section aria-labelledby="legal-license">
          <h2 id="legal-license">Copyright and license</h2>
          <p>{COPYRIGHT}. ODOS is open-source software under the {LICENSE_NAME}. <a href={LICENSE_URL} target="_blank" rel="noopener noreferrer">Read the full license text (LICENSE file)</a>.</p>
        </section>
        <ThirdParty manifest={manifest} />
      </div>
    </main>
  );
}

/** A composite component: it has several licenses; only its main one is named, with a link to the official text. */
function MainLicense({ p }: { p: LicensePackage }) {
  const what = p.kind === "Docker image" ? "Main software" : "Main license";
  const name = p.mainLicense!.name, url = p.mainLicense!.url;
  return (
    <>
      <span className="chip">{MULTIPLE}</span>
      <span className="muted"> · {what}: {url ? <a href={url} target="_blank" rel="noopener noreferrer">{name}</a> : name}</span>
    </>
  );
}

function ThirdParty({ manifest }: { manifest: LicenseManifest }) {
  const [query, setQuery] = useState("");
  const [license, setLicense] = useState("");
  const licenses = useMemo(() => [...new Set(manifest.packages.map(licenseLabel))].sort((a, b) => a.localeCompare(b)), [manifest]);
  const shown = useMemo(() => filterPackages(manifest.packages, query, license), [manifest, query, license]);
  return (
    <section aria-labelledby="legal-third">
      <h2 id="legal-third">Third-party open-source software</h2>
      {!manifest.available ? (
        <div className="alert warn" role="status">The list of third-party software is not available in this build.</div>
      ) : (
        <>
          <p>
            ODOS is built on {manifest.packages.length} open-source packages and base images, listed below with their licenses. Their full license texts and copyright notices are in{" "}
            <a href={NOTICES_URL} target="_blank" rel="noopener noreferrer">THIRD-PARTY-NOTICES.txt</a>.
          </p>
          <div className="legal-tools">
            <label className="legal-search">
              <span className="sr-only">Search packages</span>
              <input type="search" placeholder="Search packages or licenses" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <label>
              <span className="sr-only">Filter by license</span>
              <select value={license} onChange={(e) => setLicense(e.target.value)}>
                <option value="">All licenses</option>
                {licenses.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </label>
            <span className="muted small" aria-live="polite">{shown.length} shown</span>
          </div>
          <div className="legal-table-wrap">
            <table className="legal-table">
              <thead><tr><th scope="col">Package</th><th scope="col">Version</th><th scope="col">License</th><th scope="col">Type</th><th scope="col">Source</th></tr></thead>
              <tbody>
                {shown.map((p) => (
                  <tr key={`${p.kind}|${p.name}|${p.version}`}>
                    <th scope="row">{p.name}</th>
                    <td>{p.version ?? "not pinned"}</td>
                    <td>{p.licenseName ? <span className="chip">{p.licenseName}</span> : p.mainLicense ? <MainLicense p={p} /> : <span className="legal-unknown" title={p.note ?? undefined}>{UNDETERMINED}</span>}</td>
                    <td>{typeOf(p)}</td>
                    <td>{p.url ? <a href={p.url} target="_blank" rel="noopener noreferrer">{p.url.includes("npmjs.com") || p.url.includes("pypi.org") ? "Package page" : "Homepage"}<span className="sr-only"> of {p.name}</span></a> : <span className="muted">–</span>}</td>
                  </tr>
                ))}
                {shown.length === 0 && <tr><td colSpan={5} className="muted">No package matches.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            The list comes from the project's dependency lockfiles. It includes development tools and packages for other platforms, so not every entry is part of the running application. "{MULTIPLE}" marks Docker images and packages that bundle many components: the license shown is that of the main software only, not of the whole image, and the licenses of the other components have not been checked one by one. "{UNDETERMINED}" means the package does not state its license. Licenses are as declared by the packages.
          </p>
        </>
      )}
    </section>
  );
}
