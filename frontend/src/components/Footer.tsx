import { COPYRIGHT, LICENSE_NAME, LICENSE_URL } from "../legal/links";

/** The one footer of the application (rendered by App, below every screen): copyright, the project license, the Legal Notices page. */
export function Footer() {
  return (
    <footer className="site-footer">
      <div className="shell site-footer-inner">
        <span>{COPYRIGHT}</span>
        <a href={LICENSE_URL} target="_blank" rel="noopener noreferrer">{LICENSE_NAME}</a>
        <a href="#/legal">Legal Notices</a>
        <span className="muted">Non-commercial academic project (AMOS course)</span>
      </div>
    </footer>
  );
}
