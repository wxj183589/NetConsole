---
name: h3c-snmp-mib-skill
description: "H3C、HH3C、SNMP MIB、OID、MIB Browser、MIB 资源、模块依赖、OID 树、MIB 字典、产品参考表或 H3C V5/V7/V9 MIB 导入与搜索任务时使用。普通 SNMP 请求/调度使用 snmp-collector-design-skill；SSH 命令解析或纯 UI 布局不使用本 Skill。"
---

# 目标

维护 NetConsole 的 H3C MIB 资源、模块/符号/OID 关系、版本差异、产品参考表、索引和展示映射，保证 H3C MIB 可导入、搜索和追溯。

# 触发与反例

触发示例：

- “导入 H3C V7/V9 MIB 并修复模块依赖。”
- “这个 HH3C OID 在 MIB Browser 中没有显示。”
- “对比 H3C 产品参考 Excel 与现有 MIB 字典。”

不应触发：

- “实现 SNMP GETBULK 后台查询。”
- “解析 display wlan ap all 或只改 SNMP 页面布局。”

# 输入与输出

- 输入：MIB/参考资料来源、目标版本、模块/OID、复现步骤和兼容要求。
- 输出：最小 MIB 服务/Repository/页面修改、兼容性说明、测试和 H3C 节点显示验证。
- 允许修改生产代码：允许，仅限 MIB/OID 领域、相关 Repository/模型/UI 和测试；数据库或导入格式变化必须先说明兼容影响。

# 开始前读取

- `src/netconsole/services/mib_compile_service.py`、`src/netconsole/services/mib_dictionary_service.py`、`src/netconsole/services/mib_index_service.py`。
- `src/netconsole/services/mib_product_reference_service.py`、`src/netconsole/services/mib_product_reference_compare_service.py`。
- `src/netconsole/services/mib_resource_service.py`、`src/netconsole/services/mib_translation_service.py`。
- `src/netconsole/repositories/global_mib_repository.py`、`src/netconsole/repositories/site_snmp_repository.py`、`src/netconsole/models/mib_models.py`。
- `src/netconsole/ui/pages/mib_browser_page.py`、`src/netconsole/ui/pages/mib_dictionary_page.py`、`src/netconsole/ui/pages/mib_resource_page.py`。
- `tests/test_snmp_center.py` 和实际 MIB fixture/资源说明。

# 工作流程

1. 涉及 MIB/OID/MIB Browser 时优先复用现有 SNMP Center、MIB Browser、资源和字典能力，不创建重复工具。
2. 区分 H3C V5、H3C V7/V9、标准 MIB、产品参考表、Module、Symbol、OID、实例 OID 和 Trap/Notification。
3. 确认源文件组织、模块依赖、编码和来源；H3C 目录结构参考官方压缩包/版本/模块组织，不只按通用 MIB 分类。
4. MIB Browser 与 SNMP MIB 能力尽量合并为统一入口；H3C/HH3C 模块必须可见，不能只展示通用 MIB。
5. 分组、设备、地址、模块或 OID 切换后，依赖选择必须清空并按当前上下文刷新。

# 项目约束

- OID 节点至少考虑名称、数字 OID、所属 MIB、访问类型、数据类型、描述和索引信息。
- Excel/PDF/文本参考资料先确认数据源和编码；中文描述按 UTF-8 处理，历史资料用 GB18030/GBK 兜底，不因终端乱码删除内容。
- 不硬编码现场 IP、community、MAC、设备名或本机路径。
- MIB 映射与 SNMP 采集解耦；不把 UI 字段名写入采集协议。

# 验证与失败报告

- 验证 H3C MIB 导入、模块依赖、HH3C 节点搜索、OID 树、节点详情和分组切换刷新。
- 涉及旧库时验证旧 MIB 导入和已有索引；无法取得官方/真实 MIB 时明确说明仅完成 fixture 验证。
- 输出修改文件、数据库影响、旧导入兼容性、资料编码和 H3C MIB 显示步骤。

# 相关 Skills

- SNMP 请求/采集：`snmp-collector-design-skill`。
- 中文资料编码：`windows-encoding-skill`。
- 页面缺陷：`qt6-ui-fix-skill`。
