import { defineConfig, devices } from "@playwright/test";

/**
 * E2E assumes API at http://localhost:8000 and UI at http://localhost:5173
 * (e.g. `docker compose up` or local uvicorn + npm run dev).
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
