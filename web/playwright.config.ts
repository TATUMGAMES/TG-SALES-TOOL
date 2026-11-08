import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// The e2e server uses a throwaway PostgreSQL database and a fake Steam store
// (synthetic data, no network). Build the web app first: npm run build.
const root = path.resolve(process.cwd(), "..");
const python = process.env.TG_SALES_PYTHON ?? path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const server = path.join(root, "tests", "e2e_server.py");

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalTeardown: "./e2e/teardown.ts",
  outputDir: "test-results",
  use: {
    baseURL: "http://127.0.0.1:8799",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `"${python}" "${server}" --port 8799 --info-file .e2e/e2e-info.json`,
    url: "http://127.0.0.1:8799/api/health",
    timeout: 120_000,
    reuseExistingServer: false,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "tablet", use: { ...devices["Desktop Chrome"], viewport: { width: 820, height: 1180 }, hasTouch: true } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
