# Elevated Launcher

该目录保存 Windows 工具集管理员启动 helper 的源码。helper 只从标准输入接受固定
JSON schema，复核绝对 `.exe`、参数数组和工作目录后调用
`ShellExecuteExW(lpVerb="runas")`；不接受命令字符串，也不调用 PowerShell、CMD 或
Shell。

`apps/desktop_electron/scripts/build.mjs` 使用 Go 标准库和 Windows GUI 子系统构建
`dist/native/netconsole-elevated-launcher.exe`。生成的 EXE 属于构建产物，不提交仓库。
