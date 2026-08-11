import { describe, expect, it, vi } from 'vitest'

import {
  deleteDatabaseBackup,
  getDatabaseUpgradeSnapshot,
  openDatabaseBackupDirectory,
  organizeLegacyDatabaseArchives,
  restoreDatabaseBackup,
  startDatabaseUpgrade,
  validateDatabaseBackup,
} from './databaseUpgrades'

describe('database upgrade API client', () => {
  it('uses semantic profile and backup identifiers for all operations', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await getDatabaseUpgradeSnapshot()
    await startDatabaseUpgrade('profile / 07')
    await organizeLegacyDatabaseArchives()
    await validateDatabaseBackup('backup / 1')
    await restoreDatabaseBackup('backup / 1')
    await openDatabaseBackupDirectory('backup / 1')
    await deleteDatabaseBackup('backup / 1')

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/database-upgrades',
      '/api/database-upgrades/upgrade',
      '/api/database-upgrades/legacy-archives/organize',
      '/api/database-upgrades/backups/backup%20%2F%201/validate',
      '/api/database-upgrades/backups/backup%20%2F%201/restore',
      '/api/database-upgrades/backups/backup%20%2F%201/open-directory',
      '/api/database-upgrades/backups/backup%20%2F%201/delete',
    ])
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ database_kind: 'mesh_derived', profile_id: 'profile / 07' })
    expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toEqual({ confirmed: true })
    expect(JSON.parse(fetchMock.mock.calls[6][1].body)).toEqual({ confirmed: true })
  })
})
