import { defineConfig, devices } from "@playwright/test";

const pythonExecutable = process.env.E2E_PYTHON || ".venv/bin/python";
const databasePath = `/tmp/mra-playwright-${process.pid}.db`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:8102",
    channel: process.env.E2E_USE_SYSTEM_CHROME ? "chrome" : undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "mobile-chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    cwd: "../backend",
    command: `APP_ENV=development SECRET_KEY=playwright-only-secret-key-with-at-least-32-characters DATABASE_URL=sqlite+aiosqlite:///${databasePath} DEV_LOGIN_ENABLED=true DEV_LOGIN_ROLE=teacher DEEPSEEK_MOCK=true ${pythonExecutable} -m uvicorn src.main:app --host 127.0.0.1 --port 8102`,
    url: "http://127.0.0.1:8102/health/ready",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
