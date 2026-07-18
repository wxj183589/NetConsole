# `device.inventory.collect` 版本化命令 Profile 迁移记录

日期：2026-07-18
阶段：统一网络设备命令平台首个只读切片
状态：自动测试通过；真实设备待验收

## 迁移范围

- 新增 `resources/device_command_profiles.json`。
- Clean Build 将唯一源码事实源受控复制到 Backend `netconsole/assets/`，源码缺失时才使用包内资源；package smoke 校验 schema、Operation 和完整命令顺序。
- 新增 `device_command_profile_service.py`，以稳定 Operation ID 和版本化 Profile ID 选择 H3C/Comware 交换机设备详情命令。
- `h3c_collect_service.py` 不再维护或在模块导入时加载独立命令元组；执行阶段按当前 `PathResolver` 惰性解析 generic Profile。
- Profile step 记录稳定 `step_id`、顺序、输出 selector、parser/DTO contract、风险和验证证据；应用日志记录解析出的 Operation、Profile 与兼容级别。
- `command_guard.py` 增加 Operation 与 context 的固定映射校验，继续作为迁移期二次保护。

## 行为不变边界

- 命令序列仍为 `screen-length disable` 加原 11 条设备详情命令。
- 命令原文和顺序未修改。
- 单条命令失败后继续后续可执行命令的语义未修改。
- 现有 parser、Repository 写入、数据库 schema 和 FastAPI DTO 未修改。
- 设备管理 SNMP v1/v2c 不属于 CLI Profile，本次未改动。
- 现有 `CommandResult`、raw JSONL、数据库 schema 和 API DTO 均未增加 Operation/Profile 字段；执行契约持久化留给后续独立切片。

## 失败关闭

- 仅匹配 H3C / switch / Comware。
- Huawei、ZTE、未知角色和未知平台没有 H3C fallback。
- 未知软件版本只能命中显式 `generic_read_only` Profile。
- 用户可编辑 `device.remark` 不参与版本选择；精确版本只接受后续可信探测链显式传入。
- exact Profile 的 fixture 主版本必须与 selector 主版本一致，不能用 V7 样例把 V9 标成 `fixture_verified`。
- V5/V9 没有真实 fixture，因此没有声明已兼容。
- generic 执行遇到 H3C 不识别、参数错误、歧义或权限错误回显时记为命令失败/partial，不把普通错误文本记为成功。

## 验证

- Profile schema、selector、重复 ID、重复 step、危险命令和 generic 风险约束均有测试。
- H3C 采集测试核对完整命令顺序、继续执行语义、解析与 Repository 写入。
- `tests/test_device_command_profile_service.py` 覆盖 schema、重复 Profile/step ID、step 顺序、危险命令、非法 selector、未知平台和 generic fallback。
- `tests/test_h3c_collect_service.py` 核对完整命令顺序、失败继续、parser/Repository 行为和非 H3C 连接前拒绝。
- `tests/test_e10_device_command_guard.py` 核对 Operation/context 绑定、危险命令和 Profile 命令精确匹配，前缀扩展不被误放行。
- 定向测试覆盖 schema/重复键、完整 step 与命令序列、包内资源 fallback、可信版本选择、CLI 错误回显、失败 raw artifact、解析与 Repository 写入；上述 Python/测试/审计脚本 Ruff 通过。
- `audit_commands.py --json` 对经正式 loader 验证的 Profile 使用完整规范化字符串相等；无生产调用且按备注猜版本的旧 H3C Adapter/Connection/Profile 已删除，未验证命令没有混入活动目录；`--strict` 会对任何后续 deferred 项以非零退出阻断发布。

## 后续阻塞项

- AC、MR、配置、诊断、文件管理与 Agent sidecar 尚未迁移。
- `file_transfer_service.py` 的动态 SFTP username 必须进入单独强类型参数安全切片。
- Command Guard 与 Profile 的文本重复需在更多域迁移后消除。
- 真实 H3C 设备验收前保持 `REAL_DEVICE_PENDING`。
