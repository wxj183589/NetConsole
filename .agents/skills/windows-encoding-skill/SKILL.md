---
name: windows-encoding-skill
description: "Windows、PowerShell、Codex 终端、中文乱码、H3C 回显、日志、历史外部 MIB 文件、CSV/XLSX、subprocess、UTF-8、GB18030、GBK、OEM/控制台代码页或 JSONL 编码任务时使用。UI 翻译、i18n 词条设计或纯协议解析错误不使用本 Skill。"
---

# 目标

在 Windows 文件、控制台、设备输出和子进程边界统一处理中文编码，不把终端显示问题误判为文件损坏。

# 触发与反例

触发示例：

- “PowerShell/Codex 中 H3C 中文回显乱码。”
- “subprocess 输出解码失败或出现替换字符。”
- “历史 GBK CSV/MIB 描述导入后中文丢失。”

不应触发：

- “新增中英文 UI 翻译。”
- “字段解析规则错误但原始文本编码正常。”

# 输入与输出

- 输入：原始字节/文件、来源、声明编码、当前读写调用点和复现环境。
- 输出：边界层最小修复、编码判定证据、回归测试和中文内容验证方法。
- 允许修改生产代码：允许，限统一编码 helper、Adapter/文件/子进程边界及测试；不得为消除乱码删除中文或改业务字段。

# 开始前读取

- `src/netconsole/utils/text_encoding.py`、`src/netconsole/core/runtime_environment.py`、`src/netconsole/core/app_logger.py`。
- `src/netconsole/services/netmiko_connection.py`、`src/netconsole/services/connection_manager.py`、`src/netconsole/services/tool_path_resolver.py`。
- `src/netconsole/background_worker.py`、`src/netconsole/export_worker.py`、`src/netconsole/services/job_center/worker_protocol.py`。
- `tests/test_text_encoding.py` 和受影响导入/导出测试。

# PowerShell 前置

涉及中文、路径、日志、附件或设备回显前执行：

```powershell
chcp 65001 > $null
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

# 工作流程与规则

1. 不直接相信 PowerShell/Codex 终端乱码，也不用 `echo`、`cat`、默认 `Get-Content` 判断文件损坏；先检查原始字节和显式解码。
2. 源码、Markdown、JSON、YAML、TOML、CSV 和项目日志默认 UTF-8；Python 文本读写显式指定 `encoding`。
3. 外部 H3C 回显、历史日志、MIB 和 CSV 依次尝试 `utf-8-sig`、`utf-8`、`gb18030`、`gbk`；区分 OEM/控制台代码页、SSH 输出和文件编码。
4. 优先复用 `decode_text_auto`、`read_text_auto`、`read_text_with_fallback`、`clean_h3c_device_text`；新增 helper 时保持单一统一入口，不在调用点散落猜测式循环。
5. 内部 Job/Export JSONL 协议固定 UTF-8，stdout 只放协议事件；不要把外部设备编码策略套到内部协议。
6. XLSX 由 openpyxl 等库处理，不把 WPS/Excel 显示行为当作文本编码修复依据。

# 验证与失败报告

- 用 Python 从原始字节按候选编码读取，验证中文 UI、日志、MIB 描述和 CSV 往返；保留替换字符兜底的现有测试语义时必须说明原因。
- 无法取得原始字节时，不断言文件已损坏；报告终端代码页、读取 API 和剩余不确定性。
- 输出修改文件、编码策略、H3C 回显影响、CSV/XLSX 影响和中文验证步骤。

# 相关 Skills

- H3C parser：`network-command-parser-skill`。
- 历史外部 MIB 文件只按普通文本编码排查；NetConsole 不再提供 MIB/OID 产品平台。
- Worker JSONL：`netconsole-job-center-skill`。
