import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "html",
  timeout: 30_000,

  use: {
    baseURL: "http://localhost:3110",
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    command: "pnpm build && pnpm start",
    url: "http://localhost:3110",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      SKIP_ENV_VALIDATION: "1",
      PORT: "3110",
      // E2E: all API calls are intercepted by page.route(); gateway URL is
      // required by next.config.js rewrites() but never actually contacted.
      DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: "http://127.0.0.1:8100",
    },
  },
});
