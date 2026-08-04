import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    // In dev, the FastAPI backend runs separately on :8000; in production
    // the built SPA is served by that same process, so these paths are
    // already same-origin there and no proxy is needed.
    //
    // "/ask" and "/monitoring" are both API path prefixes AND client-side
    // route paths (the Ask and Monitoring pages), so a plain prefix match
    // would also swallow page navigations - bypass proxying for exactly
    // those two GET requests so Vite serves the SPA itself for the page,
    // while POST /ask and GET /monitoring/<endpoint> still proxy through.
    proxy: {
      "/ask": {
        target: "http://localhost:8000",
        bypass: (req) => (req.method === "GET" ? req.url : undefined),
      },
      "/feedback": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/monitoring": {
        target: "http://localhost:8000",
        bypass: (req) => (req.method === "GET" && req.url === "/monitoring" ? req.url : undefined),
      },
    },
  },
});
