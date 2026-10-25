// Vite builds the website into dist/. In Docker, nginx serves dist/ and
// sends /api and /auth to the backend, so the website and the API are one site.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
});
