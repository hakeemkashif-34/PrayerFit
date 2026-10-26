import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// The font files come from npm and are served by our own site, not Google Fonts.
import "@fontsource-variable/plus-jakarta-sans";
// The hadith on the landing page. 400 only, which has the ﷺ sign.
import "@fontsource/amiri/400.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
