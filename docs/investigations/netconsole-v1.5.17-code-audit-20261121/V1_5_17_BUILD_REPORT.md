# v1.5.17 构建报告

## 源码身份

- Commit：`d687ba575b27fdbc11a2013b9afc467c1bb4d07c`
- Version：`1.5.17` / `v1.5.17`
- Edition：Full only
- Published：`false`
- Build number：`0`

## 已执行构建

| 项目 | 命令/结果 |
| --- | --- |
| Python compile | `compileall src scripts` PASS |
| Ruff | 修改 Python/Ground Unattended 范围 PASS |
| Renderer | `pnpm --dir apps/desktop_renderer run build` PASS |
| Electron | `pnpm --dir apps/desktop_electron run typecheck`、`build:main` PASS |
| Backend | PyInstaller `NetConsoleBackend.exe` PASS；依赖闭包 71 distributions |
| Package smoke | PASS：health、Ground、MESH 幂等、设备迁移、中文 Worker、NOTICE/SBOM |
| Formal package gate | BLOCKED：本地分支未 Push 到 upstream，未绕过该门禁 |

Installer/Portable 为本地候选构建，使用短路径隔离 worktree 规避 NSIS 265 字符 include 路径限制；没有修改正式构建脚本或放宽安全门禁。
