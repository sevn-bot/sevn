import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

function devTarget(): string {
  const raw = process.env.SEVN_DEV_HOST ?? "127.0.0.1:8787";
  if (raw.startsWith("http://") || raw.startsWith("https://")) {
    return raw;
  }
  return `http://${raw}`;
}

const host = devTarget();

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/ws": { target: host, ws: true },
      "/auth": { target: host },
    },
  },
  test: {
    environment: "jsdom",
    passWithNoTests: true,
    include: ["tests/**/*.{test,spec}.ts", "tests/**/*.{test,spec}.tsx"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    typecheck: {
      include: ["tests/**/*.test-d.ts"],
    },
  },
});
