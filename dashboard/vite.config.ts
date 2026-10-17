/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const gateway = process.env.GATEWAY_URL ?? "http://127.0.0.1:8420";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": gateway, "/healthz": gateway } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
