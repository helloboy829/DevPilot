import { defineConfig, devices } from "@playwright/test";

const frontendPort = process.env.E2E_APPROVAL_FRONTEND_PORT ?? "3012";
const gatewayPort = process.env.E2E_APPROVAL_GATEWAY_PORT ?? "8012";
const frontendUrl = `http://localhost:${frontendPort}`;
const gatewayUrl = `http://localhost:${gatewayPort}`;
const gatewayInternalUrl = `http://127.0.0.1:${gatewayPort}`;

/** Authenticated approval E2E with a real local account and synthetic approval data. */
export default defineConfig({
  testDir: "./tests/e2e-approval-auth",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "html",
  timeout: 90_000,

  use: {
    baseURL: frontendUrl,
    trace: "on-first-retry",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      command: `uv run python scripts/run_replay_gateway.py --port ${gatewayPort} --cors ${frontendUrl}`,
      cwd: "../backend",
      url: `${gatewayUrl}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        DEER_FLOW_AUTH_DISABLED: "0",
      },
    },
    {
      command: `pnpm build && pnpm exec next start -p ${frontendPort}`,
      url: frontendUrl,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: {
        PORT: frontendPort,
        SKIP_ENV_VALIDATION: "1",
        DEER_FLOW_AUTH_DISABLED: "0",
        BETTER_AUTH_SECRET: "local-dev-secret",
        DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: gatewayInternalUrl,
      },
    },
  ],
});
