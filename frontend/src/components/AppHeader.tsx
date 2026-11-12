import { Logo } from "./Logo";

/** The workspace header: the ODOS logo with its subtitle and a minimal navigation to the two parts of this page. */
export function AppHeader() {
  return (
    <header className="site-nav">
      <a className="brand-link" href="#top" aria-label="ODOS workspace"><Logo /></a>
      <nav className="nav-links" aria-label="Workspace">
        <a href="#library" aria-current="page">Documents</a>
        <a href="#upload">Processing</a>
      </nav>
    </header>
  );
}
