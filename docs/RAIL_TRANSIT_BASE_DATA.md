# 轨道交通基础资料维护边界

## 当前状态

`/rail-transit/base-data` 是站点、区间、轨旁 AP、轨旁 AP 规划、列车和车载 MR 的统一维护入口，Feature key 为 `web.rail_transit_base_data`。页面默认锁定；正常 `persistent` Electron 受管会话可解锁并维护当前局点，`isolated_test` 始终只读并显示明确原因。普通 Server、未认证浏览器和未授权副本仍保持锁定。页面复用现有 Python Core 和当前局点 `devices.db`，不建立第二套基础资料数据库。

原独立 `/rail-transit/trackside-ap-plan` 页面和导航已删除；旧路由只重定向到 `/rail-transit/base-data?tab=trackside-ap-planning`。规划查询和在线状态刷新继续复用现有能力，但活动页面不再提供规划模板导入、模板下载或规划导出；站点来源统一通过设备管理生成并由基础资料统一保存事务提交。轨旁 AP 规划当前是一站一行的直接维护模型，只维护 AP 数量和 AP 管理 VLAN；多个站使用相同管理 VLAN 合法。IP、掩码、网关和旧 VLAN 分组数据不参与当前规划读取。详细边界见 [轨旁 AP 逐站规划](AP_MANAGEMENT_VLAN_GROUPS.md)。

基础资料和轨旁 AP 只读查询按接口独立刷新。成功接口立即更新对应数据；失败接口保留最后成功值，不会让站点、区间、AP、列车或规划整组闪空。健康检查在线但业务接口失败时，页面显示局部“部分基础资料刷新失败”提示；只有核心健康和多个核心查询持续失败才显示 Backend 整体不可用。总览在无成功缓存时用 `—` 或“加载失败”表示未知，不把接口失败统计成真实 `0`。

```text
devices.db
├─ ap_extension_points       轨旁 AP 点位、位置和里程资料
├─ ac_trackside_ap_plan      逐站 AP 规划事实
├─ devices / device_groups   列车、车载 MR 和其他静态设备
├─ rail_ap_vlan_*            历史 VLAN 分组兼容层
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
- 线路级 metadata 增加主线路径编码、站序递增/递减方向名称、递增/递减方向线路侧、`increasing_direction_leading_end`、站点来源分组和固定来源字段。线路侧默认 `increasing_direction_line_side=右线`、`decreasing_direction_line_side=左线`，局点可反转；`increasing_direction_leading_end` 仅允许 `car_1_end / car_6_end / unknown`，默认 `unknown`。方向判断基于正式节点的 `sort_order`，不直接使用节点编码。
- 站点模型包含稳定 `node_uid`、来源站点值/来源键、节点类型、路径、方向参与、结构、站台形式、中心里程、终点属性、轨道设施、端点延伸、启用和来源类型。`track_facilities` 是允许多选的正式字段，支持折返线、渡线、存车线、出入段线、站后折返线、环形折返、其他侧线和其他；`turnback_capable` 仍表示实际运营折返能力，不能由任意设施自动推断。旧 `turnback_type` 继续兼容读取和导出，其中 `pocket_track` 安全映射为折返线与存车线。旧 AP 派生站点保留为 `legacy_ap_derived`，不会启动时自动转换。
- MAIN 路径的新普通车站在手工新增、设备来源预览和模板空单元格场景默认 `underground / island`；停车场、车辆段、接轨点和其他路径默认 `unknown / unknown`。已有高架、地面、侧式等明确值不会被覆盖；设备来源再次应用到草稿时，只允许补齐 MAIN 普通站仍为 `unknown` 的字段，不在页面加载或应用启动时静默写库。
- `center_mileage_text` 保留业务原文，`center_mileage_m` 保存安全解析结果；支持 `ZDK12+345`、`YDK12+345`、`K12+345`、`12+345` 和纯米数。本字段用于后续站点定位、区间设计与方向分析，本阶段不作为 MR 方向判断硬条件，也不冒充 AP 实际覆盖里程。
- `ap_extension_points` 可能包含站点标题、设计起点等定位辅助行。Web 轨旁 AP 列表只纳入具有 `ap_name`、有效 MAC 或非空且非 `-` 的 `ap_point_code` 的记录；站点和区间派生仍读取全部定位行。
- AP 正式名称与 AP 点位编号分字段保留。AP 名称优先显示 AC 当前真实 FIT-AP 名称，未匹配时才回退基础资料名称；点位编号不写回 AP 名称。
- `AP厂商`/`ap_vendor` 是轨旁 AP 的正式可选字段，支持模板、导入预览、手工维护、DTO 和当前资料导出。只有明确填写 `H3C` 且物理 MAC 合法、末位为 `0` 时，AP Identity 才生成 H3C Radio 1/2 完整 alias；空值和其他厂商不推导。
- 列车和车载 MR 来自 `devices` 与 `device_groups`；只读取显式安全字段，不读取账号、密码、Community、Token 或隧道凭据。
- 车载 MR 的 `mr_position_code`、`physical_end` 和 `car_number` 是独立的固定安装资料：`MR-CT = CT / 1车厢端 / 1`，`MR-CW = CW / 6车厢端 / 6`。兼容字段 `role` 仍返回原名称解析结果，但不再表示运行头尾。当前运行角色只能由“实际运行方向 + `increasing_direction_leading_end` + 物理安装位置”计算为 `leading_end / trailing_end / turnback_transition / unknown`；RSSI 信号模型只做一致性验证，不能静默交换 CT/CW。
- AP、MR、设备之间不因 MAC 相同而自动合并。运行态关联继续复用现有 AC 和 Mesh-Link 匹配结果，不接管 AP Identity 生产匹配。

## 站点来源与模板

自动生成车站初稿的唯一权威来源是当前局点 `devices.db` 中设备分组标准化名称精确为 `车站` 的设备，并且只读取 `devices.station` 字段。`device.name`、`system_name`、`location`、`primary_address`、设备类型、IP 地址、名称末尾 `1/2` 或任何模糊匹配都不得用于推断站点。`station` 为空的设备只计数并在预览中返回安全设备标识，不回退到设备名。

`StationSourceDiscoveryService` 使用 SQLite `mode=ro` 与 `PRAGMA query_only` 读取 `device_groups/devices`，一次读取全部匹配设备，不受前端分页限制。来源字符串按 NFKC、空白折叠、连字符统一和大小写无关生成匹配键；`32-五乡1/32-五乡2` 这类设备名不会生成站点，只有共同的 `station=32-五乡` 会合并为一个候选并统计 `source_device_count=2`。

显式编号分隔符支持 `-`、`_`、`.`、`/`、`、`、逗号、`:` 和空格，保留节点编码前导零，并把数字记录到
`source_order_text/source_order`；普通车站再由 `source_order` 得到 `sort_order`。无分隔符且以零开头的
两位编号可直接识别；其他无分隔符两位编号只有在同批至少 3 个候选、覆盖绝大多数未解析值、编号唯一且基本
连续时才推断。`3号航站楼`、`1号线换乘站`、`101大道站` 等歧义名称不会被截断；稀疏或重复批次保持
`manual_review`。只有数字、超过 3 位数字前缀或去除明确前缀后名称为空时进入阻断错误。无数字前缀仍是合法
来源，保留完整正式站名且 `sort_order=null`。

`source_station_value` 保留原始设备字段，`source_station_key` 保存“规范站名 + 节点类型 + 路径”的稳定身份，
`canonical_station_name` 保存不含编号前缀的规范站名。以 `停车场`、`车辆段` 或非普通站名的 `车场` 结尾时
识别为特殊节点，保留 `source_order`，但默认 `path_code=UNASSIGNED`、`sort_order=null`、
`participates_in_direction=false`，不会因为编码较大被排入主线。

候选身份使用“规范站名 + 节点类型 + 路径”稳定键，不把编号前缀写入正式站名。编号写法不同但规范身份和
数值编号一致时合并来源设备数；同编号不同站名、同站名不同编号或同路径顺序重复时返回阻断冲突。一个来源
匹配多个同类型、同路径、同规范站名的正式站点时，预览改为建议 `merge_duplicates`，但仍须由用户选择保留
目标并确认差异，不会自动合并；其他多目标匹配保持人工处理。匹配依据依次公开为 `exact_source_key`、`canonical_name_and_type`、
`canonical_name`、`alias`；预览表同时显示原始值、规范站名、解析方式、可信度、正式站点、匹配依据和
建议动作。“自动匹配现有”只更新来源证据；只有用户明确选择下述“覆盖现有”时才更新允许的来源字段，人工
维护字段仍默认受保护。

来源预览只给出候选、匹配和冲突，不提供直接写库接口。每个候选明确选择“自动匹配现有 / 覆盖现有 / 新增 / 忽略 / 人工选择目标 / 合并重复项”，底部批量按钮也只应用已勾选候选。前端“从设备管理生成”和“导入模板”都只能应用到当前解锁草稿，最后仍通过全局 `validate` 与 `changes` 保存，继续保留 `base_revision`、明确确认、事务回滚和保存失败保留草稿。来源确认默认只补充 `source_station_value/source_station_key/source_kind` 以及响应中的设备数量状态；结构和站台仅在 MAIN 普通站仍为 `unknown` 时补齐默认值。设备管理中来源后来消失时只把正式站点标为 `stale`，不删除站点，也不修改 `devices` 或 `device_groups`。

## 站点选择与冲突处理

站点表的选择能力只在解锁编辑时启用，支持单选、多选、当前页全选、选择全部顺序冲突项、清空选择，以及在草稿变化后保留仍有效的稳定站点 ID。删除、覆盖和合并都只生成前端草稿变更，不会在点击操作按钮时写库；撤销选中变更从当前页面基线恢复，不会重新读取或覆盖数据库。

批量删除先调用只读 `stations/delete-preflight`，并携带当前 `base_revision`。预检统计区间起终点、轨旁 AP、规划及关系引用，并区分 `SAFE_DELETE`、`REQUIRES_MERGE` 和 `BLOCKED`；线路端点始终阻断。有引用的站点不能静默跳过或直接删除，页面逐项显示原因并要求先合并/重新指向，用户可取消阻断项后只继续安全项。保存时后端再次检查 revision 与引用。

“覆盖现有”保留正式目标的 `id`、`node_uid` 及全部引用，只允许来源默认覆盖 `code/name/sort_order/node_type/path_code/participates_in_direction` 与来源证据字段。中心里程、结构、站台、线路/服务端点、折返能力、轨道设施、端点延伸和人工备注默认保留；只有用户逐项明确勾选时才采用来源人工字段。若草稿中已存在多余来源记录，则同一个 `replace` 变更完成目标更新与来源记录清理。

“合并重复项”要求选择一个既有正式站点作为目标，并在一个 `replace` 草稿计划内迁移来源站点的区间名称引用、区间节点 UID、轨旁 AP、轨旁 AP 规划和关系引用，随后删除重复的正式站点辅助行。节点类型、路径、线路端点属性、主线顺序或中心里程差异超过 250 米时必须人工选择；任何区间在迁移后形成同名端点或相同节点 UID 自环时阻断。后端在单一 SQLite 事务中执行迁移、完整性校验和删除，失败完整回滚。

主线顺序错误按 `path_code + sort_order` 聚合为冲突组，不再重复展示同一通用文案。冲突抽屉列出具体站点，并提供保留指定项、来源覆盖、合并、修改顺序、取消某项参与方向和暂不处理；处理结果仍进入同一草稿和保存状态机。

站点模板为 XLSX，包含 `01_线路参数`、`02_线路节点`、`03_区间配置` 和 `字段说明` 四个工作表。线路参数包含线路名称、项目类型、网络类型、主线路径编码、站序递增/递减方向及对应线路侧、设备来源分组、固定来源字段 `station` 和备注；线路节点包含中心里程、多轨道设施与端点延伸字段；区间配置包含稳定生成标识、正式起终节点和只读 AP 数量/里程范围。旧三工作表模板仍可导入，缺少区间页时只提示“模板未包含区间配置”，不删除现有区间。导入预览会映射中文枚举、设施分隔符和 `是/否、true/false、1/0` 布尔值，模板文件路径和原文件内容不写入正式数据库。

桌面下载通过受控 `downloadBackendResource` 白名单、当前 Electron Session 和原子 `.part` 文件保存；取消保存不显示成功，API、IPC 或文件系统失败返回安全错误。浏览器模式继续使用原生下载。模板文件名为 `线路站点与区间基础资料模板.xlsx`，正式导出文件名为 `线路站点与区间基础资料.xlsx`；导出始终读取已保存版本，页面有未保存草稿时明确提示其不包含在导出中。

## 轨旁 AP 文件闭环

“轨旁 AP”标签页直接提供“下载模板 / 导入并预览 / 导出当前 / 导出重命名命令 / 新增轨旁 AP”。模板和当前导出均通过独立 Export Process 生成 `轨旁AP` 与 `字段说明` 两个工作表，并经 `source=trackside_ap_base` 的公共 Artifact 完成校验和受控下载。模板包含 AP 名称、点位编号、可选 AP 厂商、AP MAC、站点/区间、方向、可选里程、上联交换机/端口、供电和光缆等正式字段；FIT-AP 关联、当前光衰、来源和问题数为只读导出列。冲突和无效行可通过“导出问题明细”生成独立 XLSX Artifact；前端必须先由用户选择保存位置，再提交 Export Process。

锁定状态允许下载、导出和只读预览，不能应用；解锁后“导入 N 条有效数据到草稿”只更新 `editingDraft.aps` 和 `pendingChanges`，不调用独立写库接口，仍由页面右上角“保存并锁定”统一提交 revision 校验与事务。按钮只在没有可导入行、页面锁定或正在保存时禁用，不再要求额外确认勾选，也不因其他行存在冲突、无效或未匹配 FIT-AP 而禁用。导入空值默认 KEEP，不能清除已有里程、位置或上联资料；删除只能通过页面明确操作。

轨旁 AP 基础资料独立于 AC、FIT-AP 运行态、设备管理和上联交换机资料。点位编号与 AP MAC 至少存在一个即可导入；AP 名称、交换机、端口、光口、供电和光缆字段均可为空。AP MAC 存在时按公共规范器校验并以 `xxxx-xxxx-xxxx` 展示；MR/MESH 位置快照优先按规范化 MAC 匹配。AP 名称为空时页面、基础资料导出和 MESH 位置结果回退到点位编号。当前 FIT-AP 未发现相同 MAC 时只产生非阻断 warning，后续 AC 采集到相同 MAC 后继续自动关联。

`ap_switch_port_point_table` 兼容 `轨旁AP业务` 工作表：`AP编号/点位编号/AP点位/AP名称编号 → point_code`、`AP_MAC → mac`、`归属站点 → station`、`区间 → section/direction`、`室内交换机 → uplink_switch`、`接口名称 → uplink_port`。带编号站点保留原文到来源 metadata 后再匹配正式站名；文件中的 `AP名称` 不覆盖 AC 当前真实名称；缺少里程不阻断，MAC 为占位符的空端口行跳过。

轨旁 AP 的 `line_side` 不在主表显示或筛选，但仍保存在 `ap_extension_points`、进入基础资料 XLSX 的“线别”列并供里程与分析使用。推导优先按 AP 保存的区间身份（ID、编码、生成标识）和完整正式区间名称匹配，再使用带方向的结构化起终节点；正式区间的 `line_direction` 优先于 `direction_role`，区间名称末尾仅作旧数据兼容。空值和 `line_side_source=section_direction` 可随区间或局点映射重算，`manual/import/legacy` 非空值保持原值；冲突、方向缺失、区间不匹配或歧义进入数据质量问题。查询只做非破坏性兼容补全，实际持久化发生在受控导入或基础资料统一保存时，不执行粗暴数据库迁移。

“导出重命名命令”只读取当前局点的结构化轨旁 AP 资料或用户明确选择的未保存草稿，通过 Export Process 生成 UTF-8 BOM、Windows CRLF 的 TXT Artifact。每条命令使用唯一 MAC 和 `point_code` 生成 `wlan rename-ap <AP_MAC> <点位编号>`，空值、无效 MAC、名称已一致和不安全目标名称记录为跳过；同一 MAC 多目标或同一目标多 MAC 直接阻断。该功能只导出命令，不连接 AC、不执行命令，也不附加保存、重启、删除等高风险命令。FIT-AP 详情联动只接受按规范化 MAC 唯一匹配出的 `fit_ap_id`；未匹配或重复匹配不会打开错误详情。

“轨旁 AP 规划”标签页分为“AP 规划维护”和“AP 上线情况概览”。站点基础资料不再从规划模板导入，也不在规划页临时创建；点击“从设备管理生成站点”后，页面复用设备管理“车站”分组的 `station` 字段生成候选，先预览、处理匹配/冲突，再应用到当前基础资料草稿，最终由统一保存事务提交。维护表固定为序号、车站名称、AP 数量、AP 管理 VLAN 和备注，支持直接编辑、新增、删除、撤销、单元格校验和统一保存；车站必须匹配当前基础资料。AP 数量是当前确认应建设、应上线的有效规划值，可按现场核减调整；原设计数量和核减原因记入备注。同 VLAN 跨站合法，AC 状态、轨旁 AP 参考资料记录数和 VLAN 兼容模型均不覆盖规划值。当前活动页面不提供轨旁 AP 规划模板导入、模板下载或规划导出，旧 API 仅作为历史消费者兼容入口保留。概览表只展示规划 AP 总数量、实际上线、未上线、上线率和备注；实际上线按参考资料映射的稳定 `station_id` 汇总现有 FIT-AP 在线状态，未上线取 `max(规划值 - 实际上线, 0)`，总上线率取实际上线合计除以规划值合计。规划为 `0` 或实际上线超过规划时上线率显示 `—`，后者保留真实上线数量并显示“超规划”。未匹配有效资料的在线 AP 单独警告且不计入站点。规划查询与上线状态查询独立刷新：任一请求失败只在对应子页显示结构化错误并保留最后成功数据；上线状态失败不清空、锁定或改变规划草稿，网络/API 错误也不进入“有 N 项需要修正”的规划字段校验计数。页面同时显示 AC/FIT-AP 数据采集时间和本次查询生成时间，避免把旧采集时间误认为本次刷新时间。

轨旁 AP 业务页面、轨旁 AP 业务导出和上线概览共用当前局点的有效轨旁 AP 范围。范围按显式项目/线路/建设阶段、`work_scope_status=included`、有效 `station_id` 和稳定 AP 身份过滤并去重；暂不参与、明确排除、跨项目和未关联资源不进入正常统计。站名仅用于历史数据的唯一候选回退和最终展示，不作为聚合键；带序号与不带序号的同站名称不会生成两行。未配置建设阶段时不会按站名猜测一期或延长线。业务页面按交换机、接口、交换机光模块、LLDP、FIT-AP 资源和 FIT-AP 光衰分别记录 `loaded / partial / failed`；附加来源失败时仍返回已成功构建的候选端口行，并明确显示不可用来源。统计卡把真实 `0`、首次未加载、加载失败和部分可用分开表达。页面刷新失败时保留最后成功表格；来源不完整的快照不允许进入轨旁 AP 光衰更新或正式业务导出，避免遗漏目标或生成误导文件。

## 区间生成与统计

- `POST /api/rail-transit/base-data/section-generation-preview` 接收当前线路参数、站点草稿和区间草稿，只计算预览，不读取一轮前的站点顺序，也不写数据库。前端只选择结果并应用到 `editingDraft.sections`，最终仍由全局保存统一提交。
- 每条路径按启用、参与方向判断、普通车站和非空顺序筛选，相邻站生成递增/递减两个区间。区间名称始终使用低序站到高序站的物理站对，因此下行名称仍为“低序站-高序站-下行”，但起点和终点按实际方向反转。
- 自动区间以 `path_code + node_uid + direction_role` 形成稳定 `generation_key`。站点改名只更新显示名称，不改变身份。只更新 `auto_generated=true` 且生成标识匹配的区间；人工区间不覆盖，旧自动区间只标记 `STALE` 并默认保留，人工备注继续保留。
- MAIN 低序和高序线路端点分别使用 `endpoint:MAIN:low` 与 `endpoint:MAIN:high`，各生成两个方向的端点延伸区间。端点是正式端点节点，不伪装成普通车站；用户可在预览中取消任一方向。
- 区间 `ap_count`、`mileage_min` 和 `mileage_max` 由轨旁 AP 正式归属实时聚合。无 AP 时数量为 `0`，无有效 AP 里程时范围为 `--`；模板中的 AP 数量和里程范围只展示，导入时忽略，站点中心里程不会替代 AP 实际范围。

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
GET /api/rail-transit/base-data/stations/conflicts
GET /api/rail-transit/base-data/station-template
GET /api/rail-transit/base-data/station-template-export
GET /api/rail-transit/trackside-ap-business/plan
GET /api/rail-transit/trackside-ap-business/plan/online-status
GET /api/rail-transit/trackside-ap-business/plan/online-status/excluded
GET /api/rail-transit/trackside-ap-business/plan/online-status/unmatched
```

普通维护接口：

```text
POST /api/rail-transit/base-data/validate
POST /api/rail-transit/base-data/changes
POST /api/rail-transit/base-data/stations/delete-preflight
```

`changes` 只接受强类型实体动作、`base_revision`、局点和明确确认；凭据、Token、Community、数据库路径、表名和 SQL 均被拒绝。局点元数据（线路名称、项目类型、网络类型、备注）、站点、区间、轨旁 AP、车载 MR 和统一规划在同一请求内写入；SQLite 事务与 metadata 原子替换失败时执行补偿恢复，任何一步失败都不得留下半完成状态。

预览接口：

```text
POST /api/rail-transit/base-data/import-preview
POST /api/rail-transit/base-data/station-template-preview
POST /api/rail-transit/base-data/section-generation-preview
POST /api/rail-transit/trackside-ap-business/plan/import/preview
POST /api/rail-transit/trackside-ap-business/plan/export
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

- 支持现有 AP 模板的 XLSX/CSV 解析、标准字段 JSON，以及站点基础资料 XLSX 模板预览；最大 10 MiB、最多 5000 行。轨旁 AP 规划页不再调用规划模板导入/导出入口，站点来源统一使用设备管理站点字段预览。
- 只允许 `.xlsx`、`.csv`、`.json` 与 MIME 白名单；不接受宏工作簿。
- XLSX 使用 `data_only=True` 读取，不执行公式或宏，也不使用外部链接生成业务值。
- XLSX/CSV 仅写入系统受控临时目录，返回前由 `TemporaryDirectory` 清理；JSON 直接在内存解析。
- 旧轨旁 AP 规划模板解析和导出接口仅保留给历史消费者，不属于当前活动页面；活动页面不从模板写入规划草稿。
- 返回值只保留基础资料安全字段。账号、密码、Token、Community、Secret、Credential、上传模板原路径和用户本机绝对路径不返回、不记录。
- 预览不写 `devices.db`、`tasks.db` 或正式资料目录，不创建 Task，不生成正式资产。合并计划以 `preview_id` 保存到 `.local/runtime/base_data_import_previews/`，只包含安全字段、文件 basename/SHA-256、数据库 SHA-256、问题和 15 分钟有效期，不保存上传原文件或绝对路径；过期预览会被受控清理。
- 预览逐行返回 `CREATE / UPDATE / UNCHANGED / CONFLICT / INVALID`，并展示字段级现值、候选值、来源、动作和警告。`importable_count` 只汇总 CREATE、UPDATE 和 UNCHANGED；WARNING 不改变行的基础分类。
- `ap_switch_port_point_table`（AP 交换机端口点表）识别 `轨旁AP业务` 中的 `AP_MAC`、`AP编号`、`AP名称编号`、`归属站点`、`区间`、`室内交换机` 和 `接口名称`。带数字前缀的站点以安全来源元数据保留原值并规范为正式站名，区间末尾提取上下行；缺少里程允许导入且不会清除已有里程或备注，点位编号和有效 MAC 都缺失的占位行进入 `INVALID`。文件中的 `AP名称` 不进入点位编号字段，轨旁 AP 页面显示 AC 当前真实 AP 名称并单独显示点位编号。
- 同一 MAC 与同一点位的完全重复行只保留首条，后续计为 UNCHANGED；同一 MAC 对应不同点位、同一点位对应不同 MAC，或相同身份对应不同文件内容时，仅相关行进入 CONFLICT。已存在记录的空字段可补充为 UPDATE；非空非身份字段不同则保留正式值并产生 warning，不要求人工确认。
- 数据质量按实体分组。同一 AP 或 MR 的多个问题只占一个实体组；阻断项、警告项和仅提示项分开统计，页面不得把字段问题数误称为设备数。
- 正式库中的重复 MAC、重复静态 IP、MR 角色冲突和身份冲突仍属于数据质量阻断项。导入文件中的 AP 身份冲突和无效格式只阻断对应行，不阻断同批其他有效行；缺少 AP 正式名称、缺少 MAC或里程缺失可进入补录队列。

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
2. 线路来源字段、站点名称/编码/来源键/路径顺序/折返类型、站点/区间引用、AP MAC、里程、MR 名称/IP/端口和规划 VLAN/站点归属校验通过；轨旁 AP 规划不再接收 IP、掩码或网关字段；
3. 在一个 `BEGIN IMMEDIATE` 事务内按站点/区间、AP/MR、规划顺序写入；
4. 任一实体失败时完整回滚并保留前端修改；
5. 事务提交后仅在 AP Identity 来源 revision 变化时，以独立短事务原子重建索引；
6. 返回新 revision 和新增、更新、删除数量。

受控导入一次写入固定满足：

1. 合并预览未过期、数据库逻辑 SHA-256 未变化且 `importable_count > 0`；CONFLICT、INVALID 和未匹配 FIT-AP 不阻断其他行；
2. 调用方显式确认且安全开关为 `1`；
3. 使用 SQLite Backup API 先生成可校验备份，再在一个事务内对 CREATE/UPDATE 逐行使用 savepoint；行级约束失败回滚该行并继续，数据库不可用或最终完整性校验失败才回滚整个事务；
4. 记录操作 UUID、来源文件 basename/SHA-256、总行数、实际导入/创建/更新/不变、warning、跳过冲突/无效、未匹配 FIT-AP、问题明细、相对备份引用、数据库前后哈希和可逆字段变化；
5. 回滚前确认数据库仍等于本次写入后的哈希，避免覆盖后续修改。

同一 `preview_id` 只处理一次；重复提交返回 `ALREADY_APPLIED`，不得重复 CREATE/UPDATE。运行态字段和空值覆盖不能进入正式资料写入计划；冲突或无效行不得由前端决策绕过，只能修正来源后重新预览。

AP 点表导入、预览、确认、审计和回滚只在“轨道交通 / 基础资料”显示。AC 管理不再提供独立“导入 AP 元数据”入口；FIT-AP 运行态仍通过共享 MAC 关联读取基础资料，不建立第二套导入数据。

备份和审计位于当前局点 `files/rail_transit/base_data_import/backups/` 与 `operations/`。审计不保存凭据、连接串、源文件绝对路径或本机临时路径。

## 刷新与性能

- 总览 30 秒、AP/MR/关联运行态 15 秒、站点/区间/数据质量 60 秒。
- 页面隐藏或卸载时停止全部计时器；同类请求未结束时不重复发起。
- 页面解锁期间停止轮询并禁用分页/筛选刷新；保存、放弃或重新锁定后恢复。
- 总览、站点、区间、数据质量、轨旁 AP、列车、车载 MR、关联运行状态和导入治理接口分别落值；单个请求失败不阻止同批其他成功结果写入，失败项保留最后成功数据，下一次成功只清除自身错误。手动刷新会并行重试全部数据域。
- 单个业务接口失败时页面显示“部分基础资料刷新失败”，并可展开查看 API path、错误码、HTTP 状态、`request_id` 和原始消息，不把 `/api/health` 在线的场景描述为 Backend 整体离线。
- 只有至少两个核心接口连续 3 次发生传输级失败时才额外探测 `/api/health`；健康检查也失败后才显示“Backend 连接中断”。有接口连续失败 3 次时，对应数据域后续刷新降为 120 秒。
- AP、MR 和问题使用后端分页；`base-data/aps` 先在 SQLite 完成筛选、排序、计数、`LIMIT/OFFSET`，排除没有 AP 身份字段的空占位行，再只为当前页批量拼接 AC/MESH 轻量运行态和质量问题。普通页不得调用全量 AC AP 明细、逐 AP 查询或扫描全局质量问题；AC、Mesh-Link、Online MR 关联继续按批次读取。
- `base-data/aps` 和轨旁 AP 上线概览记录分阶段耗时及返回/总行数，超过 2 秒写 warning；诊断不进入普通响应，也不记录凭据或大对象。上线概览只返回统计和少量诊断摘要，排除项与待关联在线 AP 在用户展开时分别分页加载，并按规划、FIT-AP、AP Identity 和局点元数据 revision 使用进程内缓存。
- API client 的 15 秒查询超时不自动重试；GET 只对 502/503/504 和明确的短暂网络错误重试一次，同一路径并发 GET 复用在途 Promise。页面轮询仍须等待上一请求结束，避免慢查询形成重试或轮询堆积。

副本验收使用 `python -m scripts.maintenance.test_rail_transit_base_data_apply`。脚本复制 `devices.db` 后才预览、应用和可选回滚，并在结束时核对源库 SHA-256 与 mtime；目标副本已存在、目标与源目录重叠或缺少副本开关时直接拒绝。

## 当前限制

- 真实局点维护只允许正常持久化 Electron 受管会话；站点/区间存在 AP 引用时不能删除，车载 MR 存在 Online MR 历史时不能直接删除；
- 本阶段不自动生成停车场/车辆段接轨拓扑，不实现折返事件识别、MR 行驶方向识别、行程区段评分或启动时自动同步站点来源；`mr_end_role_service.py` 已提供运行端位语义与计算规则，但尚未接入 MESH 行程分析、页面或报告；
- 设备连接、AC 命令、Mesh-Link 刷新和 Online MR 启停；
- Agent 远程 MR 控制与 `executor=AGENT`；
- 基础资料维护页不执行 AC 采集或 MESH 身份重映射；保存/导入写任务负责在来源提交后收口 AP Identity 索引，普通页面 GET 只读；
- 离线分析和正式报告 Web 化。

自动测试只在临时局点副本验证保存、导入和回滚；宁波地铁 12 号线等正式局点的内容修改仍须在正常持久化 Electron 中人工确认。自动测试前后应核对正式 `devices.db`、bootstrap 和当前局点未变化。
