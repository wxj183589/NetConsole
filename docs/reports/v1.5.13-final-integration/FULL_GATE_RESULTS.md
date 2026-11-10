# Full Gate Results

执行命令：

```text
$env:PYTHONPATH='src'
$env:NETCONSOLE_BUILD_PYTHON='D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe'
& $env:NETCONSOLE_BUILD_PYTHON -m scripts.quality.local_gate --mode full
```

命令退出码为 `1`。按项目交接语义记录为 `FULL_LOCAL_GATE=PARTIAL`，不宣称 Full Gate PASS。

| 检查 | 结果 | 证据 |
|---|---|---|
| Workspace layout | FAIL | 既有 `.ruff_cache`、顶层 `docs`、`worktrees\test-data` 3 项违规；本轮未删除或移动 |
| Renderer full | PASS | 211 test files / 1541 tests |
| Renderer build | PASS | 有既有 large chunk warning |
| Python full | PARTIAL | 5654 passed / 14 failed / 2 skipped / 35 warnings，耗时 1801.62s |
| Electron full | PASS | 38 files / 313 tests |
| Electron typecheck/build | PASS | 通过 |
| Architecture guards | FAIL | 12 项中 3 项失败，涉及 sqlite connect 分类、命令审计候选和 MESH cache UI 业务逻辑 |
| Main contract smoke | PASS | 12 passed / 3 warnings |
| Ruff full | PASS | All checks passed |
| Docs path guards | FAIL | 2 项失败，涉及历史治理文件名和现存目录 README 缺口 |
| Git diff check | FAIL | 历史报告文件存在 trailing whitespace/空白行；未在本轮扩大清理范围 |
| Package smoke in Full Gate | BLOCKED | 安装器 upstream/clean 保护在正式构建前阻断 |

Python 的 14 项失败集中包含既有安装器诊断 mock 接口、旧字段快照以及其他治理基线问题；DataRoot 与安装器相关新增范围的定向回归通过。Full Gate 的失败项已保留为后续治理工作，不通过修改报告或绕过门禁掩盖。

## 合并后的定向回归

- Python DataRoot/installer：`46 passed`
- Electron DataRoot/packaging：`50 passed`
- Renderer DataRoot/UI：`36 passed`
- Python Ruff：PASS
- Python compileall：PASS
- Electron typecheck：PASS
- Renderer vue-tsc：PASS
- `git diff --check`（合并冲突解决后修改范围）：PASS
