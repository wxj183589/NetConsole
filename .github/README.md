# GitHub 配置

## 用途与边界

`.github/` 保存仓库级 GitHub Actions、Issue/PR 模板和自动化门禁配置。它只描述持续集成与协作流程，不承载 NetConsole 运行时配置、业务数据或设备命令实现。

## 主要入口

- `workflows/quality-gate.yml`：快速 Python、Web、Electron 质量门禁。
- `workflows/python-full-regression.yml`：Python 全量回归，由 PR、手动、每日定时或 `main` 推送触发。

两个 Workflow 都支持受控的 Windows Hosted/Self-hosted 后端选择，规则和注册边界见 [Windows Self-hosted CI](../docs/development/SELF_HOSTED_CI.md)。public 仓库的 `pull_request` 始终使用 Hosted；`main`、定时任务和受信手动运行才可选择标签为 `netconsole-ci-windows-x64` 的 Runner。

## 禁止事项

- 不在 Workflow 中写入设备凭据、真实局点路径或生产数据。
- 不使用 `continue-on-error`、批量跳过或强制推送掩盖失败。
- 不使用 `pull_request_target`，不让外部 fork PR 运行 Self-hosted；Runner 不保存 PAT、设备凭据或生产数据。
- Self-hosted 只使用仓库外的独立 Runner 工作目录，测试数据必须落在 `D:\NetConsoleTestData\<run-id>`。
- 业务逻辑必须进入 `src/netconsole` 或对应 `apps/` 模块，不能通过 Workflow 脚本绕过架构边界。

## 测试与修改

修改门禁后先在仓库根目录运行对应的 Python、Web 或 Electron 定向验证，并用 `git diff --check` 检查 YAML/Markdown 空白。全量 Python 回归的结果以 `python-full-regression` 任务日志为准。
