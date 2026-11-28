import type { DeviceTaskKind } from '../api/deviceOperations'

export const deviceTaskEntries = [
  { kind: 'diagnostic', title: '诊断收集' },
  { kind: 'backup', title: '配置备份' },
  { kind: 'upgrade_lab', title: '版本升级' },
  { kind: 'config_generate', title: '配置生成' },
] as const satisfies ReadonlyArray<{ kind: DeviceTaskKind; title: string }>
