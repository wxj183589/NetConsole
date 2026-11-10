# 合并冲突解决记录

v1.5.13 便携提交与 Ground 最新测试/启动约束在以下文件发生冲突：

- `apps/desktop_electron/scripts/dev-runtime.mjs`
- `apps/desktop_electron/scripts/package-smoke.mjs`
- `apps/desktop_electron/src/main/development-data-root.ts`
- `apps/desktop_electron/tests/global-setup.ts`
- `apps/desktop_electron/tests/packaging.test.ts`

解决原则：

- 保留 v1.5.13 引入的精确 Workspace 识别：只有位于 `NetConsole-Workspace\worktrees` 且存在主仓库 `.git` 时才归一化测试根。
- 保留 Ground 分支已有的测试、启动和包 smoke 断言。
- 将 portable marker、`NETCONSOLE_PORTABLE_BUILD` 和免安装脚本断言与既有 packaging 断言合并。
- 不改变真实业务数据根，不把系统 Temp 变成永久数据根。

冲突处理后 `git diff --check`（排除历史报告中的既有格式告警）和相关测试通过。
