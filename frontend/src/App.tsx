import { useSyncExternalStore } from "react";
import { Footer } from "./components/Footer";
import DemoApp from "./demo/DemoApp";
import LegalNotices from "./legal/LegalNotices";

/** Two pages, told apart by the URL hash ("#/legal"; the workspace's own anchors are plain "#library"). The workspace stays mounted, so an upload or open result survives a visit to the Legal Notices. The footer is outside both pages: one footer on every screen. */
const onLegalRoute = () => window.location.hash === "#/legal";
const subscribe = (notify: () => void) => { window.addEventListener("hashchange", notify); return () => window.removeEventListener("hashchange", notify); };

export default function App() {
  const legal = useSyncExternalStore(subscribe, onLegalRoute);
  return (
    <div className="app">
      <div className="app-page" hidden={legal}><DemoApp /></div>
      {legal && <LegalNotices />}
      <Footer />
    </div>
  );
}
