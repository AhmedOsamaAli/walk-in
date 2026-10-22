import react from "@vitejs/plugin-react";
import { defineConfig, type ProxyOptions } from "vite";

const proxy: Record<string, ProxyOptions> = {
  "/api": { target: "http://127.0.0.1:8770" },
};

// The policy the production server sends. Preview serves the build under it, so a build that needs an inline
// script or a remote font fails there first. Google Identity Services (the sign-in button) needs its library, its
// stylesheet, its iframes and its endpoints, listed by their parent URLs as Google recommends:
// https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid#content_security_policy
const GOOGLE_SIGN_IN = "https://accounts.google.com/gsi/";
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  `script-src 'self' ${GOOGLE_SIGN_IN}client`,
  `style-src 'self' 'unsafe-inline' ${GOOGLE_SIGN_IN}style`,
  "img-src 'self' data: https:",
  "font-src 'self'",
  `connect-src 'self' ${GOOGLE_SIGN_IN}`,
  `frame-src ${GOOGLE_SIGN_IN}`,
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
    headers: {
      "Content-Security-Policy": CONTENT_SECURITY_POLICY,
      // As the server sends it: Google's sign-in popup must be able to answer the page that opened it.
      "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
    },
  },
  build: {
    outDir: "dist",
    // Inlined assets become data: URLs, which the policy blocks for fonts.
    assetsInlineLimit: 0,
  },
});
