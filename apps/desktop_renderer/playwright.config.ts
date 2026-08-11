import { defineConfig, devices } from '@playwright/test'

const chromePath = process.env.NETCONSOLE_CHROME_PATH
  || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const viewports = [
  { width: 1280, height: 720 },
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
]
const scales = [1, 1.25, 1.5]

export default defineConfig({
  testDir: './tests/visual/e2e',
  outputDir: '../../.local/tests/renderer-visual',
  timeout: 30_000,
  fullyParallel: true,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:4175',
    browserName: 'chromium',
    headless: true,
    launchOptions: { executablePath: chromePath },
    colorScheme: 'light',
  },
  projects: viewports.flatMap((viewport) => scales.map((scale) => ({
    name: `${viewport.width}x${viewport.height}@${String(scale * 100)}%`,
    use: { ...devices['Desktop Chrome'], viewport, deviceScaleFactor: scale },
  }))),
  webServer: {
    command: 'pnpm exec vite --host 127.0.0.1 --port 4175',
    url: 'http://127.0.0.1:4175/tests/visual/',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
})
