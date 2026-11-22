import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// the ODOS website's fonts, self-hosted: Audiowide (logo, display headings) and Geist (text)
import "@fontsource/audiowide/latin-400.css";
import "@fontsource-variable/geist/wght.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
