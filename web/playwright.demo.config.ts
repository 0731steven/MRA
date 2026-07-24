import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "demo-pages.spec.ts",
  fullyParallel: false,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173/MRA/",
    channel: process.env.E2E_USE_SYSTEM_CHROME ? "chrome" : undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "demo-desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "demo-mobile", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: "VITE_STATIC_PREVIEW=true npm run build -- --base=/MRA/ --outDir=dist && npm run preview -- --host 127.0.0.1 --port 4173 --outDir dist --base=/MRA/",
    url: "http://127.0.0.1:4173/MRA/",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
