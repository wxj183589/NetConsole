import { defineConfig, devices } from '@playwright/test'

const chromePath = process.env.NETCONSOLE_CHROME_PATH
  || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const viewports = [
  { width: 1280, height: 720 },
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
]
const scales = [1, 1.25, 1.5]
const matrixProjects = [
  { name: 'matrix-1280x720@100%-zh-CN-light', viewport: { width: 1280, height: 720 }, scale: 1 },
  { name: 'matrix-1280x720@150%-zh-CN-dark', viewport: { width: 1280, height: 720 }, scale: 1.5 },
  { name: 'matrix-1920x1080@100%-zh-CN-light', viewport: { width: 1920, height: 1080 }, scale: 1 },
  { name: 'matrix-1920x1080@125%-en-dark', viewport: { width: 1920, height: 1080 }, scale: 1.25 },
  { name: 'matrix-1920x1080@150%-zh-CN-light', viewport: { width: 1920, height: 1080 }, scale: 1.5 },
  { name: 'matrix-2560x1440@100%-en-light', viewport: { width: 2560, height: 1440 }, scale: 1 },
  { name: 'matrix-2560x1440@150%-en-dark', viewport: { width: 2560, height: 1440 }, scale: 1.5 },
]

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
    testIgnore: /visual-matrix\.visual\.spec\.ts/,
  }))).concat(matrixProjects.map(({ name, viewport, scale }) => ({
    name,
    testMatch: /visual-matrix\.visual\.spec\.ts/,
    use: { ...devices['Desktop Chrome'], viewport, deviceScaleFactor: scale },
  }))),
  webServer: {
    command: 'pnpm exec vite --host 127.0.0.1 --port 4175',
    url: 'http://127.0.0.1:4175/tests/visual/',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
})
