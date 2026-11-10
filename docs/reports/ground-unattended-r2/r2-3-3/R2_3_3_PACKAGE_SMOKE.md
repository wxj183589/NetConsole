# R2.3.3 package-smoke

## 实际命令

```text
cd D:\study\NetConsole-Workspace\worktrees\r2-3-3-ground-unattended\apps\desktop_electron
pnpm run smoke:package
```

退出码：`1`。

Renderer/Electron 主进程准备步骤通过，但正式安装器保护在 `scripts.build.build_installer --prepare-identity` 处停止：

```text
INSTALLER BUILD FAILED
正式安装器要求 Git 工作区干净
```

本任务明确禁止清理/覆盖其他修改、禁止 push 和正式发布，因此没有绕过该保护，也没有生成安装版/免安装版 PASS。该失败是候选工作树 dirty / 发布身份保护，不能解释为 Syslog 业务失败。

结论：`PACKAGE_SMOKE=NOT_AVAILABLE`，`RELEASE_READINESS=NOT_READY`。后续需在经审阅的干净、允许发布流程的提交环境中重新执行。
