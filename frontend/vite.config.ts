import react from "@vitejs/plugin-react";
import { defineConfig, type ProxyOptions } from "vite";

const proxy: Record<string, ProxyOptions> = {
  "/api": { target: "http://127.0.0.1:8770" },
};

// The policy the production server sends. Preview serves the build under it, so a build that needs an inline
// script or a remote font fails there first.
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy },
  preview: {
    port: 4173,
    strictPort: true,
    proxy,
    headers: { "Content-Security-Policy": CONTENT_SECURITY_POLICY },
  },
  build: {
    outDir: "dist",
    // Inlined assets become data: URLs, which the policy blocks for fonts.
    assetsInlineLimit: 0,
  },
});
