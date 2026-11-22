import { Logo } from "./Logo";

/** The workspace header: the ODOS logo with its subtitle and a minimal navigation to the parts of this page. On the Legal Notices page the links lead back to the workspace. */
export function AppHeader({ legal = false }: { legal?: boolean }) {
  return (
    <header className="site-nav">
      <a className="brand-link" href={legal ? "#/" : "#top"} aria-label="ODOS workspace"><Logo /></a>
      <nav className="nav-links" aria-label="Workspace">
        <a href={legal ? "#/" : "#library"} aria-current={legal ? undefined : "page"}>Documents</a>
        <a href={legal ? "#/" : "#upload"}>Processing</a>
        {legal && <a href="#/legal" aria-current="page">Legal Notices</a>}
      </nav>
    </header>
  );
}
