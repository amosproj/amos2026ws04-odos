import { useEffect, useState } from "react";
import { api } from "./api";
import { DocumentHome } from "./components/DocumentHome";
import { Icon, type IconName } from "./components/Icon";
import { Workspace } from "./components/Workspace";
import { VIEWS, routeFromHash, type Route, type View } from "./documentLibrary";

const NAV_ICONS: Record<View, IconName> = { documents: "files", processing: "activity", reviews: "review" };

function ApiStatus() {
  const [up, setUp] = useState<boolean | null>(null);
  useEffect(() => {
    let dead = false;
    const check = () => api.health().then(() => !dead && setUp(true), () => !dead && setUp(false));
    void check();
    const t = window.setInterval(check, 15000);
    return () => { dead = true; window.clearInterval(t); };
  }, []);
  return (
    <div className={`api-status ${up === null ? "" : up ? "up" : "down"}`} role="status" title="Local ODOS API (http://127.0.0.1:8000)">
      <span className="dot" aria-hidden="true" />
      <span className="api-text">{up === null ? "Checking API…" : up ? "API connected" : "API unreachable"}</span>
    </div>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash(window.location.hash));
  useEffect(() => {
    const onHash = () => setRoute(routeFromHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  // a document is a child of the library: the Documents entry stays highlighted
  const current: View = route.kind === "view" ? route.view : "documents";

  return (
    <div className={`shell${route.kind === "doc" ? " compact" : ""}`}>
      <aside className="sidebar">
        <a className="brand" href="#/" aria-label="ODOS – Document Library">
          <span className="logo" aria-hidden="true"><Icon name="file" size={16} /></span>
          <span className="brand-text">
            <span className="brand-name">ODOS</span>
            <span className="brand-sub">Normative Document Intelligence</span>
          </span>
        </a>
        <nav aria-label="Main navigation">
          <ul className="nav">
            {VIEWS.map((v) => (
              <li key={v.view}>
                <a href={v.hash} className={`nav-item${current === v.view ? " active" : ""}`} aria-current={current === v.view ? "page" : undefined} title={v.label}>
                  <Icon name={NAV_ICONS[v.view]} size={17} />
                  <span className="nav-label">{v.label}</span>
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <ApiStatus />
      </aside>
      <div className="content">
        {route.kind === "doc" ? <Workspace key={route.id} id={route.id} /> : <DocumentHome key={route.view} view={route.view} />}
      </div>
    </div>
  );
}
