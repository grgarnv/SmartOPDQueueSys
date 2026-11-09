import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During the migration the React app lives under /app/ and the legacy UI keeps "/" (docs/FRONTEND_MIGRATION.md).
// Dev: Vite proxies /api (including the /api/stream SSE stream) to the Python server, so the browser sees one
// origin and the SameSite=Strict session cookie works unchanged.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  // the server CSP (default-src 'self') blocks data: URIs, so every asset ships as a file
  build: { assetsInlineLimit: 0 },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
});
