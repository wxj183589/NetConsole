# 轨道交通基础资料维护边界

## 当前状态

`/rail-transit/base-data` 是站点、区间、轨旁 AP、轨旁 AP 规划、列车和车载 MR 的统一维护入口，Feature key 为 `web.rail_transit_base_data`。页面默认锁定；正常 `persistent` Electron 受管会话可解锁并维护当前局点，`isolated_test` 始终只读并显示明确原因。普通 Server、未认证浏览器和未授权副本仍保持锁定。页面复用现有 Python Core 和当前局点 `devices.db`，不建立第二套基础资料数据库。

原独立 `/rail-transit/trackside-ap-plan` 页面和导航已删除；旧路由只重定向到 `/rail-transit/base-data?tab=trackside-ap-planning`。规划查询、导入预览、导出和 Task Center 继续复用现有能力，规划编辑由基础资料统一保存事务提交。

```text
devices.db
├─ ap_extension_points       轨旁 AP 点位、位置和里程资料
├─ devices / device_groups   列车、车载 MR 和其他静态设备
└─ AC 当前资源表             FIT-AP、光衰和接入信息
        |
        v
RailTransitBaseDataQueryService（mode=ro + query_only）
        |
        v
RailTransitBaseDataApplicationService
        |
        v
revision 校验 + SQLite BEGIN IMMEDIATE 单事务
```

站点和区间仍不是独立主表，而是由 `ap_extension_points` 派生。人工新增或补充编码、顺序和备注时写入带 `__base_station__` / `__base_section__` 标识的位置辅助行；这些行不会进入轨旁 AP 列表。查询不得初始化 schema、执行 migration、更新时间戳或写缓存。

## 编辑会话

- 页面初始状态为 `LOCKED`，解锁后停止轮询，避免服务端刷新覆盖编辑区。
- 编辑会话记录 `site_id`、`base_revision` 和 `loaded_at`；`base_revision` 同时覆盖当前 SQLite 逻辑内容和 `site_meta.json` 的规范化内容。
- 点击解锁时先把 Pinia 查询结果转换为纯 DTO 草稿，禁止直接克隆或修改 Vue reactive proxy；修改只保存在 Renderer 编辑区，不自动写库。保存前先调用校验接口，保存时后端在 `BEGIN IMMEDIATE` 后再次核对 revision。
- revision 不一致返回 `BASE_DATA_REVISION_CONFLICT`，不得以后提交静默覆盖先提交。
- 锁定、刷新、顶层页签切换、离开路由和关闭窗口均保护未保存修改；全局确认框提供取消、放弃并锁定、保存并锁定。
- 保存失败保留编辑区和 dirty 状态；成功后刷新服务端事实并自动锁定。

## 领域模型

- 局点沿用当前 Site 模型；本阶段不改变“一条线路一个局点”的既有方式。
- 站点由 AP 点位的 `station_name`、区间起终点派生。
- 区间由 `section_name + 起点 + 终点 + 线别` 派生；站点为空但区间有效是合法资料。
- `ap_extension_points` 可能包含站点标题、设计起点等定位辅助行。Web 轨旁 AP 列表只纳入具有 `ap_name`、有效 MAC 或非空且非 `-` 的 `ap_point_code` 的记录；站点和区间派生仍读取全部定位行。
- AP 正式名称与 AP 点位编号分字段保留。正式名称为空时页面可显示点位编号，但不得把点位编号写回为正式名称。
- 列车和车载 MR 来自 `devices` 与 `device_groups`；只读取显式安全字段，不读取账号、密码、Community、Token 或隧道凭据。
- 当前设备名中的 `MR-CW` 在 Web 角色筛选中映射为尾端 `TC`，原始设备名称不改变；`MR-CT` 映射为 `CT`。
- AP、MR、设备之间不因 MAC 相同而自动合并。运行态关联继续复用现有 AC 和 Mesh-Link 匹配结果，不接管 AP Identity 生产匹配。

## 正式资料、导入来源与运行态

三类数据必须分层，不得相互伪装：

- 正式资料：当前局点 `devices.db` 中的 AP 扩展点位和设备资料，是 Web 查询与合并比较的基线。
- 导入来源：官方点表、AP 扩展表和用户上传文件，只提供候选值与来源证据；文件名、SHA-256、行号和字段来源进入预览，不把本机绝对路径写入审计。
- 运行态：AC FIT-AP、AC Mesh-Link、Agent 包和 Online MR 的状态、IP、RSSI、光衰与当前关联，只用于展示或候选提示，不自动回写正式身份和位置。

字段策略集中在 `src/netconsole/services/rail_transit/source_policy.py`。AP 只允许 MAC 精确匹配，其次正式名称精确匹配；不使用 DHCP IP、模糊名称、里程相近或当前 Mesh 关联自动合并。MR 按设备 ID、静态 IP、MAC、名称精确匹配，多个键指向不同实体时直接标记冲突。正式值与低优先级候选不同则进入人工确认，不静默覆盖。

## 里程、IP 与 MAC

里程解析只在后端复用 `src/netconsole/utils/mileage.py`：

| 线路语义 | 前缀 |
| --- | --- |
| 左线 / 下行 | `ZDK` |
| 右线 / 上行 | `YDK` |
| 出段线 | `CDK` |
| 入段线 | `RDK` |

API 同时返回原文、标准显示、数值米、前缀、合法状态和错误摘要。不合法文本不得自动猜测；前缀与明确线别不一致时返回 warning。

MAC 比较支持 `xxxx-xxxx-xxxx`、冒号、两位连字符和 12 位纯十六进制格式，统一按 12 位值比较，页面使用冒号格式显示。AP MAC 与 MR MAC 分域查重。

同一局点静态设备 IP 必须唯一；车载 MR 即使当前设备类型沿用 `Cloud-AP`，仍按静态设备处理。非车载 FIT-AP/Cloud-AP 的 DHCP 地址不进入静态 IP 冲突判断。

## API

查询和编辑会话接口：

```text
GET /api/rail-transit/base-data/summary
GET /api/rail-transit/base-data/stations
GET /api/rail-transit/base-data/sections
GET /api/rail-transit/base-data/aps
GET /api/rail-transit/base-data/aps/{ap_id}
GET /api/rail-transit/base-data/trains
GET /api/rail-transit/base-data/trains/{train_id}
GET /api/rail-transit/base-data/mrs
GET /api/rail-transit/base-data/mrs/{mr_id}
GET /api/rail-transit/base-data/issues
GET /api/rail-transit/base-data/issues/groups
GET /api/rail-transit/base-data/import-policies
GET /api/rail-transit/base-data/relations
GET /api/rail-transit/base-data/revision
```

普通维护接口：

```text
POST /api/rail-transit/base-data/validate
POST /api/rail-transit/base-data/changes
```

`changes` 只接受强类型实体动作、`base_revision`、局点和明确确认；凭据、Token、Community、数据库路径、表名和 SQL 均被拒绝。局点元数据（线路名称、项目类型、网络类型、备注）、站点、区间、轨旁 AP、车载 MR 和统一规划在同一请求内写入；SQLite 事务与 metadata 原子替换失败时执行补偿恢复，任何一步失败都不得留下半完成状态。

预览接口：

```text
POST /api/rail-transit/base-data/import-preview
```

受控导入与只读审计接口：

```text
POST /api/rail-transit/base-data/import-apply
GET  /api/rail-transit/base-data/import-operations
GET  /api/rail-transit/base-data/import-operations/{operation_id}
GET  /api/rail-transit/base-data/import-operations/{operation_id}/changes
POST /api/rail-transit/base-data/import-operations/{operation_id}/rollback
```

`import-apply` 只接受 `preview_id`、局点、明确确认、字段决策和预期数据库 SHA-256；不能传数据库路径、表名、SQL 或自由业务字段。回滚接口默认关闭。不存在通用 PUT、PATCH、DELETE 或 SQL 接口。

## 导入预览安全

- 支持现有 AP 模板的 XLSX/CSV 解析，并支持标准字段 JSON；最大 10 MiB、最多 5000 行。
- 只允许 `.xlsx`、`.csv`、`.json` 与 MIME 白名单；不接受宏工作簿。
- XLSX 使用 `data_only=True` 读取，不执行公式或宏，也不使用外部链接生成业务值。
- XLSX/CSV 仅写入系统受控临时目录，返回前由 `TemporaryDirectory` 清理；JSON 直接在内存解析。
- 返回值只保留基础资料安全字段。账号、密码、Token、Community、Secret、Credential 和用户字段不返回、不记录。
- 预览不写 `devices.db`、`tasks.db` 或正式资料目录，不创建 Task，不生成正式资产。合并计划以 `preview_id` 保存到 `.local/runtime/base_data_import_previews/`，只包含安全字段、文件 basename/SHA-256、数据库 SHA-256、问题和 15 分钟有效期，不保存上传原文件或绝对路径；过期预览会被受控清理。
- 预览逐行返回 `CREATE / UPDATE / UNCHANGED / SKIP / CONFLICT / NEEDS_CONFIRMATION`，并展示字段级现值、候选值、来源、动作和警告。
- 数据质量按实体分组。同一 AP 或 MR 的多个问题只占一个实体组；阻断项、警告项和仅提示项分开统计，页面不得把字段问题数误称为设备数。
- 重复 MAC、重复静态 IP、MR 角色冲突和身份冲突属于阻断项。缺少 AP 正式名称、缺少 MAC、里程缺失等可进入补录队列，但不得绕过冲突检查。

2026-07-14 的宁波地铁 12 号线只读治理口径为“5C-6A 来源策略与实体分组 v1”：2726 条字段问题、951 个实体组、blocking 0。此前的 2723 是旧规则统计；统计变化来自规则重新分类，不代表数据库发生写入，判断数据是否变化仍以 `devices.db` SHA-256 和 mtime 为准。

## 受控写入

普通维护由 `RailTransitBaseDataApplicationService` 编排，受控导入仍由 `RailTransitBaseDataImportService` 编排；两者复用同一 `RailTransitBaseDataRepository` 和写入 Guard，不新增主数据库。页面默认锁定，后端必须同时通过以下开关：

```text
Feature Registry: web.rail_transit_base_data_write
RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED=1       # Server/副本脚本的显式开关
NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE=1       # 仅带 copy_validation 标记的副本
NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE=1       # 正式局点脚本额外授权
RAIL_TRANSIT_BASE_DATA_ROLLBACK_ENABLED=1     # 回滚独立开关
```

Electron Desktop 受管会话由短期 `desktop_session_token` 显式启用正式局点写入，不依赖环境变量；该能力只在 `NETCONSOLE_STORAGE_MODE=persistent` 时成立。`isolated_test` 即使存在桌面会话令牌也返回 `ISOLATED_TEST_READONLY`，不得写入测试局点。普通 Server/浏览器不会因为 Electron 参数获得该能力。副本还必须在局点 `site_meta.json` 中保存 `base_data_write_scope=copy_validation` 与真实源库 SHA-256。只有环境双开关不能把正式局点伪装为副本。

普通维护一次保存固定满足：

1. 页面持有的 `base_revision` 与当前数据库一致；
2. 站点/区间引用、AP MAC、里程、MR 名称/IP/端口和规划 IP/VLAN 校验通过；
3. 在一个 `BEGIN IMMEDIATE` 事务内按站点/区间、AP/MR、规划顺序写入；
4. 任一实体失败时完整回滚并保留前端修改；
5. 返回新 revision 和新增、更新、删除数量。

受控导入一次写入固定满足：

1. 合并预览未过期、数据库逻辑 SHA-256 未变化、无阻断项或待确认项；
2. 调用方显式确认且安全开关为 `1`；
3. 使用 SQLite Backup API 先生成可校验备份，再在一个事务内执行 CREATE/UPDATE；
4. 记录操作 UUID、来源文件 basename/SHA-256、创建/更新/跳过/冲突数、相对备份引用、数据库前后哈希和可逆字段变化；
5. 失败事务全部回滚；回滚前还要确认数据库仍等于本次写入后的哈希，避免覆盖后续修改。

同一 `preview_id` 只处理一次；重复提交返回 `ALREADY_APPLIED`，不得重复 CREATE/UPDATE。`NEEDS_CONFIRMATION` 必须逐字段选择保留正式值或采用导入值，后端重新校验；blocking 冲突、运行态字段和空值覆盖不能由前端决策绕过。

备份和审计位于当前局点 `files/rail_transit/base_data_import/backups/` 与 `operations/`。审计不保存凭据、连接串、源文件绝对路径或本机临时路径。

## 刷新与性能

- 总览 30 秒、AP/MR/关联运行态 15 秒、站点/区间/数据质量 60 秒。
- 页面隐藏或卸载时停止全部计时器；同类请求未结束时不重复发起。
- 页面解锁期间停止轮询并禁用分页/筛选刷新；保存、放弃或重新锁定后恢复。
- 连续失败 3 次后保留最后成功数据并把后续刷新降为 120 秒。
- AP、MR 和问题使用后端分页；AC、Mesh-Link、Online MR 关联按批次读取，禁止逐行查询。

副本验收使用 `python -m scripts.maintenance.test_rail_transit_base_data_apply`。脚本复制 `devices.db` 后才预览、应用和可选回滚，并在结束时核对源库 SHA-256 与 mtime；目标副本已存在、目标与源目录重叠或缺少副本开关时直接拒绝。

## 当前限制

- 真实局点维护只允许正常持久化 Electron 受管会话；站点/区间存在 AP 引用时不能删除，车载 MR 存在 Online MR 历史时不能直接删除；
- 设备连接、AC 命令、Mesh-Link 刷新和 Online MR 启停；
- Agent 远程 MR 控制与 `executor=AGENT`；
- AP Identity 生产接管；
- 离线分析和正式报告 Web 化。

自动测试只在临时局点副本验证保存、导入和回滚；宁波地铁 12 号线等正式局点的内容修改仍须在正常持久化 Electron 中人工确认。自动测试前后应核对正式 `devices.db`、bootstrap 和当前局点未变化。
