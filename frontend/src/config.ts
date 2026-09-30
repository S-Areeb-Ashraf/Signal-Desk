const configuredApiUrl = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL || "";
const isLocalApiUrl = /^(https?:\/\/)?(127\.0\.0\.1|localhost)(:\d+)?$/i.test(
  configuredApiUrl,
);
const isDeployedHost =
  typeof window !== "undefined" &&
  !["localhost", "127.0.0.1"].includes(window.location.hostname);

// Use Vercel's /api rewrite if a local .env value is accidentally bundled for production.
export const API_URL = isLocalApiUrl && isDeployedHost ? "" : configuredApiUrl;
