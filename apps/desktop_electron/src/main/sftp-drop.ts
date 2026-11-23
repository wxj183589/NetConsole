import { lstat, realpath } from 'node:fs/promises'
import { dirname, parse, resolve } from 'node:path'
import { normalizeAbsolutePath } from './path-access'

export async function validateDroppedFilePaths(value: unknown): Promise<void> {
  if (!Array.isArray(value) || value.length > 10000) throw new Error('拖入文件数量超过限制')
  const visited = new Set<string>()
  for (const item of value) {
    const path = normalizeAbsolutePath(item)
    if (!(await lstat(path)).isFile()) throw new Error('拖入项不是普通文件')
    let cursor = path
    while (cursor !== parse(cursor).root && !visited.has(cursor)) {
      visited.add(cursor)
      const attrs = await lstat(cursor)
      if (attrs.isSymbolicLink()) throw new Error('拖入路径包含符号链接或 Junction')
      // Real path aliases must not cross the selected content namespace.
      const canonical = resolve(await realpath(cursor))
      if (canonical.toLowerCase() !== resolve(cursor).toLowerCase()) throw new Error('拖入路径包含重定向')
      cursor = dirname(cursor)
    }
  }
}
