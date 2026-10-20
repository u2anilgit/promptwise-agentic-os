import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Browser smoke test against a throwaway, seeded gateway (scripts/e2e_gateway.py) serving the built bundle.
// Uses an installed browser channel (msedge by default) so no browser download is needed.
// Run: npm run build && npm run e2e
const port = Number(process.env.E2E_PORT ?? 8435);
export const STATE_DIR = process.env.E2E_STATE ?? join(tmpdir(), "promptwise-dashboard-e2e");
const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const python =
  process.env.E2E_PYTHON ??
  (process.platform === "win32" ? join(repo, ".venv", "Scripts", "python.exe") : join(repo, ".venv", "bin", "python"));

export default defineConfig({
  testDir: "e2e",
  testMatch: "*.e2e.ts",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: process.env.E2E_CHANNEL ?? "msedge",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${python}" -m scripts.e2e_gateway --state "${STATE_DIR}" --port ${port}`,
    cwd: repo,
    url: `http://127.0.0.1:${port}/healthz`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
