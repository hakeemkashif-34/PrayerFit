import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// The font files come from npm and are served by our own site, not Google Fonts.
import "@fontsource-variable/plus-jakarta-sans";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
