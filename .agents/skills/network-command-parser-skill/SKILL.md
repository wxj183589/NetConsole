---
name: network-command-parser-skill
description: "H3C/Comware display 命令、SSH/Telnet/Netmiko 回显、提示符、分页符、配置采集、FIT-AP、AC、Mesh 或在线 MR CLI parser 任务时使用。设备管理 SNMP、纯 UI 布局或 Excel 样式任务不使用本 Skill。"
---

# 目标

新建、修复或评审可追溯的 H3C/Comware 命令输出解析器，兼容版本、空格、分页、命令回显、提示符和字段缺失。

# 触发与反例

触发示例：

- “解析 display wlan ap all/address/radio 并合并 AP。”
- “修复 `[sysname-probe]` 提示符导致的回显解析失败。”
- “Channel Busy、Peer Radio 或 mesh-link Active 字段没识别。”

不应触发：

- “修改设备管理 SNMP v1/v2c 连接测试。”
- “修复 Qt 页面遮挡或 Excel 列宽。”

# 输入与输出

- 输入：原始回显、设备/Comware 版本、命令列表、预期结构和兼容样例。
- 输出：纯 parser/adapter 修改、原始数据保留说明、fixture 测试和失败样例。
- 允许修改生产代码：允许，限 Parser/Adapter/相关 Domain service 和测试；不得在 parser 中访问 UI、数据库或擅自改采集命令。

# 开始前读取

- `src/netconsole/adapters/h3c/`、`src/netconsole/parsers/`、`src/netconsole/parsers/h3c/`。
- `src/netconsole/services/h3c_collect_service.py`、`src/netconsole/services/h3c_ac_collect_service.py`。
- `src/netconsole/services/command_guard.py`、`src/netconsole/services/command_reference_service.py`、`src/netconsole/utils/text_encoding.py`。
- 相关 `tests/fixtures/h3c/` 和 parser/service 测试。

# 工作流程

1. 保留完整 raw log，再从副本结构化解析；不得为得到字段删除原始回显。
2. 不把单个样例当唯一格式；比较真实 fixture、测试、版本差异和字段缺失。
3. 提示符兼容 `<sysname>`、`[sysname]`、`[sysname-probe]`，避免把命令回显识别成提示符。
4. 采集前优先发送 `screen-length disable`；命令失败记录错误并继续可继续命令，不默认中断整批任务。
5. `display current-configuration` 与 `display saved-configuration` 做差异时，只取 `#version` 到 `#return` 区间。
6. `display wlan ap all`、address、radio 分别解析，按可验证的 AP 名称/MAC/IP 证据合并；不假设 AP ID 跨来源稳定唯一。
7. `display wlan mesh-link` 保留 Active、PeerMac、Peer Radio、RSSI、发送/接收忙度等可用字段。

# 项目约束

- Parser 只做 raw → structured，不访问 QWidget、不写数据库、不生成报告。
- MAC、接口、里程和名称归一化复用现有工具；不硬编码局点、车号、设备、IP、MAC 或本机路径。
- 设备命令以现有 profile/`command_guard.py` 为事实源；用户要求保持的命令顺序和原文本不得修改。
- 外部/H3C 文本按 UTF-8 优先、GB18030/GBK 兜底，编码判断集中在边界层。

# 验证与失败报告

- 每个 parser 必须有样例文本测试或最小可复现验证，覆盖成功、空输出、字段缺失、截断、命令回显、三类提示符和乱码风险。
- 无真实多版本样例时明确说明兼容性仅基于现有 fixture，不声称覆盖所有 Comware 版本。
- 输出修改文件、raw log 路径/保留情况、失败命令处理、归一化规则和测试命令。

# 相关 Skills

- 在线 MR 命令链：`netconsole-online-mr-skill`。
- 编码边界：`windows-encoding-skill`。
