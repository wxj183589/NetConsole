export declare function parsePackageApIdentityStartupSmoke(rawValue: unknown): string[]

export declare function assertProductionApIdentityStartupSmokeLogs(input: {
  scenario: string
  exitCode: number | null
  electronLog: string
  backendLog: string
}): true

export declare const packageApIdentityStartupSmokeScenarios: readonly string[]
