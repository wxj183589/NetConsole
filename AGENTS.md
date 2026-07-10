# Codex 项目规则

## 语言
- 默认使用中文回复。
- 保留中文 UI 文案、中文注释、中文日志字段，不要因为终端乱码就删除中文。

## 编码
- 项目所有文本文件默认 UTF-8。
- Python 读写文本必须显式指定 encoding="utf-8"。
- 读取 H3C 设备回显、MIB、日志、历史导出文件时，优先尝试 utf-8-sig / utf-8，失败后再尝试 gb18030 / gbk。
- 如果 PowerShell 或 Codex 终端显示中文乱码，不得直接判断业务数据损坏，必须先检查文件编码和原始字节。

## Windows / PowerShell
涉及中文、路径、日志、附件时，执行命令前先设置：

chcp 65001 > $null
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

## 项目约束
- 开发前先读取 docs 目录和现有代码结构。
- 不要沿用旧项目假设；以当前仓库实际代码和文档为准。
- 后续新增功能必须遵守 `docs/ARCHITECTURE.md`。
- 后续普通后台任务和导出任务必须遵守 `docs/JOB_CENTER.md`。
- UI 页面禁止承载长任务和业务重逻辑；超过 300ms 的 IO、CPU、网络任务进入 Job Center，所有导出进入独立进程。
- 修改后说明影响范围、验证方法、是否涉及编码/日志/中文显示。
