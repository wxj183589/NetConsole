# NetConsole v1.5.16 测试报告

## 已执行

| 范围 | 结果 | 当前证据 |
| --- | --- | --- |
| Python 修复定向集 | PASS | Ground API/Schedule/Syslog 95 passed；resident/usability 69 passed；Syslog 安全集 31 passed |
| Python 全量 | PASS | 5620 passed / 2 skipped / 35 warnings；JUnit：5622 tests、0 failures、0 errors、1742.990s |
| Renderer 修复定向集 | PASS | MR 图表模式 2 files / 4 tests；其余页面定向集均通过 |
| Renderer 全量 | PASS | 211 files / 1544 tests |
| Renderer build | PASS | `vue-tsc -b && vite build`；3431 modules transformed |
| Electron contract | PASS | 38 files / 315 tests；typecheck、main/preload build PASS |
| Architecture | PASS | 12/12 checks，0 findings、0 waived |
| Main contract smoke | PASS | 12 passed |
| Repository / Workspace / docs | PASS | root layout、workspace layout、docs 13 passed、Ruff、diff-check |

最终 Python JUnit 证据位于 Workspace 测试目录：`test-data/NetConsole/netconsole-v1516-maintenance-20261120-python-final-head.xml`，不纳入产品提交。

## 定向覆盖

- 默认关闭、Heartbeat 排除列车与空选择拒绝。
- Syslog 只读检查、精确 JOIN/EXIT、source rule 禁写和状态流转。
- Storage Audit 缺报告与有效零容量的区分。
- Quick Ping 内部字段净化。
- 关闭阶段缺少 `task_snapshots` 表。
- 车站视图默认折叠、服务端顺序保持和关系图退役。
- 路由退役与安全跳转。

## 非自动化限制

- 未在 Windows 10 20H2 实机运行 Electron。
- 未连接真实 V5/V7/V9 设备；设备写配置测试仅使用 Mock。
- 未完成 8 小时连续运行。
- 未把 jsdom、build 或 Mock 结果冒充真实 GUI/现场验收。
- Python 全量的 35 条警告主要为第三方 Starlette 弃用警告；另有 1 条 Paramiko 测试转发线程关闭时的 EOF 警告，未产生 failure/error。
