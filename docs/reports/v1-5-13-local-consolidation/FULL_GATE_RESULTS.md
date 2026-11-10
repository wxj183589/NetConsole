# Full Gate 结果

命令：

```powershell
$env:PYTHONPATH='src'
$env:NETCONSOLE_BUILD_PYTHON='D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe'
& $env:NETCONSOLE_BUILD_PYTHON -m scripts.quality.local_gate --mode full
```

结果：`FULL_LOCAL_GATE=FAIL`，不是本地整合代码 PASS。

| 套件 | 结果 |
| --- | --- |
| Root/Workspace layout | PASS（Repository-only scope） |
| Renderer full | 211 files / 1541 tests PASS |
| Renderer build | PASS，保留既有大 chunk warning |
| Python full | 5629 passed / 37 failed / 2 skipped |
| Electron full/typecheck/build | 38 files / 313 tests PASS；build PASS |
| Main contract smoke | 12 passed |
| Ruff | PASS |
| Architecture guards | FAIL，3/12：direct SQL、device command audit、UI business logic 未分类项 |
| Docs path guards | FAIL，既有 broken evidence links、transient report 文件名和 README 缺口 |
| Package smoke | 未完成；正式安装器 clean/upstream 保护阻断，未绕过 |

Python 失败主要集中在既有 Production/Storage maintenance 的 `worktrees` 路径固定契约、profile/storage benchmark、架构/文档治理；Ground、AC、DataRoot、SiteStorage、Schema 和 changelog 定向回归为 634 passed / 1 skipped。

结论：`FULL_LOCAL_GATE=PARTIAL`，`RELEASE_READINESS=NOT_READY`。不因本地集成完成而提升为正式发布通过。
