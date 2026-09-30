import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const apiUrl = env.VITE_API_URL || env.VITE_API_BASE_URL || "";
  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_DEV_SERVER_PORT || 5173),
      ...(apiUrl ? { proxy: { "/api": apiUrl } } : {}),
    },
    build: { outDir: "dist" },
  };
});