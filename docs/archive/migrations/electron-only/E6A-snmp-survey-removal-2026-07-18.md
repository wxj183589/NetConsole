# E6A：SNMP Center、MIB/OID 平台与无线勘测删除归档

日期：2026-07-18
版本：v1.3.9
分支：`refactor/electron-only`

## 1. 决策

本阶段按产品决策正式删除以下能力，不再保留为 `DISABLED`、`BLOCKED` 或 `FUTURE_REBUILD`：

- SNMP Center；
- 通用 SNMP 查询、批量采集、GETBULK、SET、Trap、Poll 和拓扑；
- MIB Browser、MIB/OID 字典、产品参考、编译索引及版本化 H3C MIB 归档；
- 无线勘测、热力图及其专用导出链。

同步删除对应 Feature/profile、Model、Repository、Application Service、Job/Export handler、路径 helper、测试、Skills、开源依赖声明和发布资源。已删除 Feature ID 由 `REMOVED_FEATURE_IDS` 防御集合拦截，旧 profile 不能恢复入口。

## 2. 明确保留

### 设备管理 SNMP

仅保留设备管理内部的 SNMP v1/v2c 只读基础能力：

- v1、v2c 独立启用开关；
- 端口、RO community、超时和重试；
- 连接测试；
- 固定基础 OID 的 GET、GETNEXT 和有行数上限的 WALK，用于设备基础识别。

不支持 SNMPv3、RW community、SET、任意 OID、MIB 上下文或通用批量采集。API/DTO 不回显 community，日志继续执行凭据脱敏。

### 网络工具无线扫描

网络工具中的 Windows 无线扫描是独立能力，保留现有页面、扫描源、历史、Raw、详情和导出。原无线勘测的数据库、勘测工程、热力图和专用导出不再作为它的依赖。

## 3. 数据安全边界

- 新建 `devices.db` 不再创建 SNMPv3、RW community 或 Context 字段。
- 旧 `devices.db` 中已存在的历史列不删除、不改名、不清空；当前 Model、Repository、API 与导入导出忽略它们。
- 历史 `snmp.db`、MIB 用户目录、局点 `snmp/` 与 `topology/` 文件不读取、不创建、不自动删除。
- 本阶段没有重建数据库、删除用户行、迁移真实凭据或清理用户文件。

## 4. 依赖与资源

- 删除仓库跟踪的 H3C V5/V7/V9 MIB 归档及 `resources/builtin_mibs` 说明。
- 删除 pysnmp 与 Pillow 的活动依赖/许可证声明；历史版本变更记录仍保留为历史事实。
- 删除 `h3c-snmp-mib-skill` 与 `snmp-collector-design-skill`，防止后续任务把已删除平台当作活动产品能力。

## 5. 验证边界

自动验证覆盖：设备 SNMP v1/v2c 模型与 Client、旧库列非破坏性兼容、设备管理 API/导入导出、AC CLI-only 拒绝 SNMP source、Feature 墓碑、Job Registry、文件契约、命令目录、Vue 设备页及无线扫描页、Ruff、JSON/文档链接和构建。

本阶段没有可用真实 SNMP 设备，因此不声明真实设备连接通过。完成后的设备管理 SNMP 状态仍为 `REAL_DEVICE_PENDING`。

提交前结果：

- Python 定向组合：168 项通过，真实设备 smoke 1 项因未提供私有配置按预期跳过；
- Vue：58 个测试文件、174 项通过，生产构建通过；
- 改动 Python 文件 Ruff 与 `py_compile` 通过；
- Feature/profile、开源声明和命令目录 JSON 解析通过；
- 当前文档布局与相对链接检查 4 项通过；
- `git diff --check` 通过。
