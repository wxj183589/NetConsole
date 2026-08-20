# Windows Self-hosted CI

NetConsole 以本地 Local Quality Gate 作为主要开发验证事实源；GitHub Actions 是可选远端复核，Windows Job 可以在受控的本机 Runner 上执行。该机制是一次性的 Runner 后端选择，不是 Hosted 失败后的自动重试：Job 排队后不会在两种后端之间跳转。

## 选择规则

- `pull_request`（包括 public repository 的 fork PR）始终使用 `windows-latest`，不执行 Self-hosted。
- `main` 推送和定时回归读取仓库变量 `NETCONSOLE_CI_RUNNER_MODE`。值为 `self-hosted` 时使用自定义标签 `netconsole-ci-windows-x64`；缺失、`hosted` 或其他值均使用 Hosted。
- `workflow_dispatch` 提供 `runner_mode`：`auto` 遵循上述变量，`hosted` 强制 Hosted，`self-hosted` 强制自定义标签。只允许受信维护者手动触发。
- 两个 Workflow 共用同一选择规则和测试逻辑；不使用 `continue-on-error`，也不把失败转换成提示。

Self-hosted Runner 离线时，选择它的任务会保持排队，直到 Runner 上线或 GitHub 的排队时限到达；这不是自动回退。首次启用建议先用 `workflow_dispatch` 选择 `self-hosted`，确认完整门禁成功后再设置仓库变量。

## 注册 Runner

1. 在仓库 GitHub 页面打开 **Settings → Actions → Runners → New self-hosted runner**。
2. 选择 **Windows / x64**，复制 GitHub 页面为当前仓库生成的下载、解压和 `config.cmd` 命令；注册令牌只在该页面临时使用，绝不写入仓库、Issue、日志或脚本。
3. 按页面提示为 Runner 添加自定义标签 `netconsole-ci-windows-x64`。不要把计算机名、用户名或路径写进 `runs-on`。
4. 推荐把 Runner 安装在仓库之外，例如 `D:\GitHubActions\NetConsoleRunner`，使用独立的普通 Windows 用户（不授予管理员权限）。如需后台运行，按 GitHub 页面生成的服务安装提示操作，不自行猜测服务参数。
5. 在 **Settings → Actions → Runners** 确认状态为 Online 后，再把仓库变量 `NETCONSOLE_CI_RUNNER_MODE` 设为 `self-hosted`。

## 机器边界

Runner 机器不得保存 GitHub PAT、SSH 私钥、设备真实密码、SNMP community 或生产共享凭据；不得连接现场生产网络、NAS 或真实设备，也不得读取 `D:\NetConsoleData`。不要把 Runner 与日常开发工作区复用，保留 GitHub Runner 自己的工作目录，让 `actions/checkout` 管理该目录。

仓库测试已经由 `tests/conftest.py` 强制使用 `RuntimeMode.TEST` 和唯一的 `D:\study\test-data\NetConsole\<run-id>`，并在会话结束时只清理自己的目录。Runner 预检还会拒绝把测试根设为 checkout 工作区；它只报告 OS、架构和 Python/Node/pnpm/Git 版本，不创建或删除业务数据。

## 维护清单

- 定期更新 Windows、Python 3.13.9、Node 24、pnpm 11.9 和 Git，并确认自定义标签仍存在。
- Runner 断线时先查看 **Actions → Runners**，不要通过修改 Workflow 绕过门禁。
- 任何让外部 PR 使用 Self-hosted 的改动都必须先完成安全评审；本仓库默认禁止该路径。

官方参考：[添加 Self-hosted Runner](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)、[在 Workflow 中使用 Runner](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow)、[Self-hosted Runner 要求](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)。
