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

站点和区间仍不新增独立主表。正式站点/区间资料写入带 `__base_station__` / `__base_section__` 标识的位置辅助行，AP 旧扩展资料只作为兼容补充；这些辅助行不会进入轨旁 AP 列表。设备管理只作为站点初稿的只读来源，不会在页面打开、轮询或预览时写入数据库。查询不得初始化 schema、执行 migration、更新时间戳或写缓存。

## 编辑会话

- 页面初始状态为 `LOCKED`，解锁后停止轮询，避免服务端刷新覆盖编辑区。
- 编辑会话记录 `site_id`、`base_revision` 和 `loaded_at`；`base_revision` 同时覆盖当前 SQLite 逻辑内容和 `site_meta.json` 的规范化内容。
- 点击解锁时先把 Pinia 查询结果转换为纯 DTO 草稿，禁止直接克隆或修改 Vue reactive proxy；修改只保存在 Renderer 编辑区，不自动写库。保存前先调用校验接口，保存时后端在 `BEGIN IMMEDIATE` 后再次核对 revision。
- revision 不一致返回 `BASE_DATA_REVISION_CONFLICT`，不得以后提交静默覆盖先提交。
- 锁定、刷新、顶层页签切换、离开路由和关闭窗口均保护未保存修改；全局确认框提供取消、放弃并锁定、保存并锁定。
- 保存失败保留编辑区和 dirty 状态；成功后刷新服务端事实并自动锁定。

## 领域模型

- 局点沿用当前 Site 模型；本阶段不改变“一条线路一个局点”的既有方式。
- 站点查询优先读取正式 `__base_station__` 资料，再用 AP 点位的 `station_name`、区间起终点作为兼容补充；设备管理来源只用于预览、来源设备数和 `matched/stale/conflict/manual/legacy` 状态。
- 区间由 `section_name + 起点 + 终点 + 线别` 派生；站点为空但区间有效是合法资料。
- 线路级 metadata 增加主线路径编码、站序递增/递减方向名称、`increasing_direction_leading_end`、站点来源分组和固定来源字段。`increasing_direction_leading_end` 仅允许 `car_1_end / car_6_end / unknown`，默认 `unknown`；方向判断基于正式节点的 `sort_order`，不直接使用节点编码。
- 站点模型包含来源站点值、来源键、节点类型、路径、方向参与、结构、站台形式、端点、折返、启用和来源类型。旧 AP 派生站点保留为 `legacy_ap_derived`，不会启动时自动转换。
- `ap_extension_points` 可能包含站点标题、设计起点等定位辅助行。Web 轨旁 AP 列表只纳入具有 `ap_name`、有效 MAC 或非空且非 `-` 的 `ap_point_code` 的记录；站点和区间派生仍读取全部定位行。
- AP 正式名称与 AP 点位编号分字段保留。正式名称为空时页面可显示点位编号，但不得把点位编号写回为正式名称。
- 列车和车载 MR 来自 `devices` 与 `device_groups`；只读取显式安全字段，不读取账号、密码、Community、Token 或隧道凭据。
- 车载 MR 的 `mr_position_code`、`physical_end` 和 `car_number` 是独立的固定安装资料：`MR-CT = CT / 1车厢端 / 1`，`MR-CW = CW / 6车厢端 / 6`。兼容字段 `role` 仍返回原名称解析结果，但不再表示运行头尾。当前运行角色只能由“实际运行方向 + `increasing_direction_leading_end` + 物理安装位置”计算为 `leading_end / trailing_end / turnback_transition / unknown`；RSSI 信号模型只做一致性验证，不能静默交换 CT/CW。
- AP、MR、设备之间不因 MAC 相同而自动合并。运行态关联继续复用现有 AC 和 Mesh-Link 匹配结果，不接管 AP Identity 生产匹配。

## 站点来源与模板

自动生成车站初稿的唯一权威来源是当前局点 `devices.db` 中设备分组标准化名称精确为 `车站` 的设备，并且只读取 `devices.station` 字段。`device.name`、`system_name`、`location`、`primary_address`、设备类型、IP 地址、名称末尾 `1/2` 或任何模糊匹配都不得用于推断站点。`station` 为空的设备只计数并在预览中返回安全设备标识，不回退到设备名。

`StationSourceDiscoveryService` 使用 SQLite `mode=ro` 与 `PRAGMA query_only` 读取 `device_groups/devices`，一次读取全部匹配设备，不受前端分页限制。来源字符串按 NFKC、空白折叠、连字符统一和大小写无关生成匹配键；`32-五乡1/32-五乡2` 这类设备名不会生成站点，只有共同的 `station=32-五乡` 会合并为一个候选并统计 `source_device_count=2`。

默认解析 `^\d+[-－—_].+` 形式的 station 值，保留节点编码前导零并把数字转为普通车站主线顺序；没有数字前缀时不丢弃候选，只提示需要人工确认顺序。以 `停车场`、`车辆段` 或非普通站名的 `车场` 结尾时识别为特殊节点，默认 `path_code=UNASSIGNED`、`sort_order=null`、`participates_in_direction=false`，不会因为编码较大被排入主线。

来源预览只给出候选、匹配和冲突，不提供直接写库接口。前端“从设备管理生成”和“导入模板”都只能应用到当前解锁草稿，最后仍通过全局 `validate` 与 `changes` 保存，继续保留 `base_revision`、明确确认、事务回滚和保存失败保留草稿。来源确认默认只补充 `source_station_value/source_station_key/source_kind` 以及响应中的设备数量状态；结构、站台、顺序、路径、端点、折返、启用和备注等人工字段不会被来源同步覆盖。设备管理中来源后来消失时只把正式站点标为 `stale`，不删除站点，也不修改 `devices` 或 `device_groups`。

站点模板为 XLSX，包含 `01_线路参数`、`02_线路节点` 和 `字段说明` 三个工作表。线路参数包含线路名称、项目类型、网络类型、主线路径编码、站序递增/递减方向、设备来源分组、固定来源字段 `station` 和备注；线路节点包含来源站点值、节点编码/名称、节点类型、路径、主线顺序、方向参与、结构、站台、端点、折返、启用和备注。导入预览会映射中文枚举和 `是/否、true/false、1/0` 布尔值，模板文件路径和原文件内容不写入正式数据库。

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
GET /api/rail-transit/base-data/station-source-preview
GET /api/rail-transit/base-data/station-template
GET /api/rail-transit/base-data/station-template-export
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
POST /api/rail-transit/base-data/station-template-preview
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

- 支持现有 AP 模板的 XLSX/CSV 解析、标准字段 JSON，以及站点基础资料 XLSX 模板预览；最大 10 MiB、最多 5000 行。
- 只允许 `.xlsx`、`.csv`、`.json` 与 MIME 白名单；不接受宏工作簿。
- XLSX 使用 `data_only=True` 读取，不执行公式或宏，也不使用外部链接生成业务值。
- XLSX/CSV 仅写入系统受控临时目录，返回前由 `TemporaryDirectory` 清理；JSON 直接在内存解析。
- 返回值只保留基础资料安全字段。账号、密码、Token、Community、Secret、Credential、上传模板原路径和用户本机绝对路径不返回、不记录。
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
2. 线路来源字段、站点名称/编码/来源键/路径顺序/折返类型、站点/区间引用、AP MAC、里程、MR 名称/IP/端口和规划 IP/VLAN 校验通过；
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
- 本阶段不实现区间拓扑自动生成、停车场/车辆段接轨拓扑、折返事件识别、MR 行驶方向识别、行程区段评分或启动时自动同步站点来源；`mr_end_role_service.py` 已提供运行端位语义与计算规则，但尚未接入 MESH 行程分析、页面或报告；
- 设备连接、AC 命令、Mesh-Link 刷新和 Online MR 启停；
- Agent 远程 MR 控制与 `executor=AGENT`；
- AP Identity 生产接管；
- 离线分析和正式报告 Web 化。

自动测试只在临时局点副本验证保存、导入和回滚；宁波地铁 12 号线等正式局点的内容修改仍须在正常持久化 Electron 中人工确认。自动测试前后应核对正式 `devices.db`、bootstrap 和当前局点未变化。
