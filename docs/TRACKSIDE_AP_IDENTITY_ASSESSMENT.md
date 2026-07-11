# 轨旁 AP Identity 只读接入评估

## 1. 背景

AP identity 阶段 1～3 已完成通用只读 resolver、AC FIT-AP/扩展信息 shadow 和光衰 shadow。轨旁 AP 业务是下一类高风险消费者：一行数据同时表达 AP、交换机、接口、LLDP、光衰、位置和在线状态，不能用单个 AP key 替代整个关系。

本阶段只评估当前实现和阶段 4.1 的只读 shadow 接入点，没有修改轨旁页面、聚合器、缓存、详情定位、导出、Repository SQL、数据库 schema 或业务规则。

当前有两条轨旁数据加载路径：

1. 轨道交通主页面：`TracksideApServicePage.refresh_async()` → `TracksideApBusinessLoadThread` → `load_trackside_ap_business_snapshot()` → `build_trackside_ap_business_rows()`。
2. AC 兼容任务：`ac_trackside_business_refresh` → `_ac_trackside_business_refresh()` → `build_trackside_ap_business_rows()`。

两条路径共享核心聚合器，但输入准备、异步生命周期和返回结构不同。阶段 4.1 不能只覆盖其中一条。

## 2. 当前轨旁 AP 数据来源

| 数据 | 当前读取位置 | 作用 | 是否是 AP identity 来源 |
| --- | --- | --- | --- |
| FIT-AP 资源 | `AcRepository.list_all_fit_ap_resources_with_metadata()` | AP UUID、MAC、名称、序列号、AC UUID、IP、当前状态、位置和扩展信息 | 是，主要 Candidate 来源 |
| AP 扩展信息 | `AcRepository._enrich_resources_with_extensions()` 间接并入资源 | 站点、区间、里程、方向、上联交换机/端口和工程属性 | 不是独立主身份；当前按 MAC、再名称附加 |
| 轨旁规划 | `get_active_trackside_pvid_plan()` | 按站点的管理 VLAN/PVID 识别候选轨旁端口，提供容量规划 | 否，只是范围和规划来源 |
| 设备管理 | `DeviceRepository`、车站设备组 | 交换机 `device_uuid`、名称、系统名、地址和所属站点 | 是交换机身份来源，不是 AP identity |
| 交换机接口 | `DeviceFactRepository.list_device_interfaces()` | `device_uuid + interface_name` 拓扑行、链路、描述、PVID、VLAN | 否，是 topology identity |
| 当前 LLDP | `list_lldp_neighbors()` | 从交换机端口取得邻居 MAC，并连接交换机接口和 AP 候选 | 是观测证据，不是 AP 主身份 |
| 历史 LLDP | `list_latest_ap_lldp_histories()`、离线台账 | 当前 LLDP 缺失时恢复历史交换机和接口关联 | 是历史拓扑证据，不是当前 AP 主身份 |
| 交换机光衰 | `list_optical_modules()` | 交换机端口光功率、模块和链路状态 | 状态来源，不是身份来源 |
| FIT-AP 光衰 | `list_all_fit_ap_optical()` | AP 侧光功率、当前/历史邻居交换机接口和 AP 字段 | 状态及关联来源，不应成为新 AP 真源 |
| AP 历史 | 资源、LLDP、Radio、光衰历史表 | 离线时间、旧拓扑、详情和导出趋势 | 历史来源 |
| AC 当前状态 | FIT-AP 资源的 `state/state_raw/state_display` | 判断 AC 当前在线、Idle/离线 | 状态来源 |
| 离线记录 | `build_offline_ap_ledger()` | 将离线 AP 与最后 LLDP、交换机接口和站点关联 | 派生历史/展示来源 |

FIT-AP 资源的 metadata join 优先 `ap_uuid`，并保留名称 fallback；扩展信息再按规范化 MAC、名称附加。因此轨旁聚合接收到的资源已经混合运行态身份、metadata 和扩展位置字段，但扩展信息不直接决定 AP 主身份。

站点、区间、里程、方向只描述位置。它们可以作为 resolver 的辅助 evidence，不能单独确定 AP。PVID、VLAN、交换机接口和端口描述只能确定候选拓扑范围。

## 3. 当前 AP 匹配和 lookup 流程

### 3.1 候选端口

`is_trackside_ap_interface()` 先排除三层接口，再按以下任一条件选择候选端口：

- 接口描述包含 `AP`。
- 接口 PVID 命中当前站点的轨旁规划 VLAN。
- 两者同时命中。

这里得到的是交换机端口，不代表已经识别出 AP。

### 3.2 当前和历史 LLDP 关联

每个候选端口依次读取当前接口、交换机光模块和当前 LLDP：

1. 当前 LLDP 的 `neighbor_mac` 被规范化后，先在 FIT-AP 资源 MAC 索引中查找。
2. 当前 LLDP 缺少邻居 MAC时，按交换机名称/系统名和接口查询历史 LLDP。
3. 历史 LLDP 可提供 AP UUID、AP MAC、AP 名称和旧邻居关系。
4. 若仍未找到，使用 FIT-AP 光衰记录中的 `neighbor_device_name + neighbor_interface` 回退。

当前代码把 LLDP 邻居 MAC用于 AP MAC lookup，但 LLDP MAC 可能来自设备、接口、Radio 或 BSSID 语义。阶段 4.1 必须记录证据和歧义，不能直接把所有 LLDP MAC 视为 AP MAC。

### 3.3 FIT-AP 和光衰索引

核心聚合器建立以下索引：

- 光衰：AP MAC、`serial/MAC/name` identity、AP 名称看似 MAC、邻居交换机+接口。
- 资源：AP MAC、`serial/MAC/name` identity。
- 历史 LLDP：交换机名称/系统名+接口。

`ap_identity_key()` 当前优先级是 `serial_number → ap_mac → ap_name`，没有包含 AP UUID 或 AC UUID。字典索引和去重也没有显式 AC 作用域，相同 MAC、序列号或名称跨 AC 时可能覆盖或合并。

### 3.4 行合并和状态

聚合完成后先按 AP `serial/MAC/name` 合并，再按 `site + switch identity + interface` 合并拓扑重复行。后者是轨旁行的稳定 topology identity：

```text
site + switch device_uuid/name + normalized interface
```

状态继续由现有规则决定：交换机原始光模块数据、接口链路、AP 光衰、AC Idle、离线台账和历史 LLDP共同参与。交换机接口不是 AP identity；identity shadow 不得计算或改写光衰、离线和链路状态。

### 3.5 单 AP 更新范围

轨旁单 AP 更新使用 `ap_uuid → ap_mac → ap_name` 的任一命中筛选当前行和 FIT-AP 资源；再优先使用当前轨旁行中的交换机身份，缺失时回退历史 LLDP，最后扩大为站点或全量交换机范围。阶段 4.1 不得让新 resolver 改变采集目标或 fallback 范围。

## 4. 双击打开详情链路

### 4.1 页面分发

`TracksideApServicePage` 只对特定列响应双击：

- `interface_name`：打开交换机接口光衰历史。
- `ap_mac` 或 `ap_name`：调用 `open_ap_detail_from_trackside()`。

页面从当前筛选、分页后的 `current_trackside_page_rows()` 取得行，因此双击依赖页面内存中的 `trackside_rows`，不直接读取持久化轨旁缓存。

### 4.2 AP 详情异步解析

页面把行内 `ac_device_uuid/ap_uuid/ap_mac/ap_name` 提交到 `trackside_fit_ap_detail_resolve`：

1. 若同时有 AC UUID 和 AP UUID，handler 直接返回该目标，不额外验证资源是否仍存在。
2. 否则读取全部带 metadata/扩展信息的 FIT-AP 资源。
3. 优先规范化 AP MAC 精确匹配。
4. MAC 未命中时才按 AP 名称大小写无关匹配。
5. 无匹配时页面显示未找到；多匹配时显示选择框；单匹配直接打开详情。

名称/MAC fallback 当前不使用 AC 作用域。它依赖 AC 当前资源表；AP 扩展信息只随资源 enrichment 进入结果，不是详情 resolver 的主匹配字段。

### 4.3 详情窗口后续加载

`FitApDetailDialog` 再提交 `fit_ap_detail_load`，在选定 AC 内按 AP UUID、再名称读取资源，并用解析后的 AP UUID加载当前光衰、metadata 和光衰摘要。因此第一次 resolver 选错 AC/AP 后，后续详情也会沿用该选择。

当前 AP 详情窗口只保存在 `detail_windows` 中，没有按 AP identity 复用的详情数据缓存。交换机接口历史窗口则按 `device_uuid/name + interface_name` 复用。

### 4.4 当前测试时序

MAC 和名称双击测试会创建真实 `BackgroundProcessManager` 任务，并通过 `process_events_until()` 等待详情窗口构造。完整 `test_ac_management.py` 共享 Qt/异步对象时可能出现三秒等待超时；代表用例在独立 pytest 进程中通过。该问题属于测试生命周期基础设施，本阶段不修改页面或异步实现。

## 5. 缓存和历史数据链路

| 缓存/历史 | 当前用途 | 阶段 4.1 边界 |
| --- | --- | --- |
| `TracksideApServicePage.trackside_rows` | 当前页面聚合结果；配合 `has_loaded/dirty/load_generation` 避免重复加载和丢弃旧请求 | 可在结果旁附加内存 shadow 摘要；不得改变行、分页和 generation |
| `trackside_ap_view_cache` | schema 以 `site_id + switch_uuid + interface` 唯一；仓库生产代码内只发现 Vehicle MR lookup 读取，当前轨旁页面没有读写入口 | 不写、不改 schema；不能把 cache row 当 AP 主身份 |
| 离线 AP JSON cache | 提供离线统计和导出上下文 | 不附加 identity 写回；离线 shadow 只读使用当次 ledger row |
| FIT-AP 资源历史 | 还原在线/离线变化和历史状态 | 后续只读 evidence；不改变历史 key |
| AP LLDP 历史 | 离线 AP 和当前 LLDP 缺失时恢复交换机/接口 | 可旁路比较 AP 绑定；不能覆盖当前 LLDP或写主 identity |
| AP 光衰历史 | 详情摘要、导出最后有效光功率和处置记录 | 可旁路诊断；不能改阈值、异常和历史选择 |
| 交换机光衰历史 | 以 `device_uuid + normalized interface` 查询 | 保持 topology identity，不解析成 AP identity |
| 详情任务上下文 | `detail_resolve_jobs[job_id]` 仅记录任务类型 | 可在 result 中附加 shadow；不得改变 finished/failed 或选择框行为 |

`trackside_ap_view_cache` 与页面所谓“缓存”不是同一件事：页面缓存是当前进程内的聚合行；数据库表是独立派生结构，目前主要被 Vehicle MR lookup 消费。

## 6. 字段和标识冲突

| 风险 | 当前表现 | 后果 |
| --- | --- | --- |
| AP UUID 未进入核心 `ap_identity_key()` | 聚合/去重优先 serial、MAC、name | 已有 UUID 仍可能被较弱键折叠 |
| 缺少 AC 作用域 | 全量资源 MAC/name 索引和详情 fallback 不带 AC UUID | 跨 AC 重复时覆盖、歧义或选错详情 |
| AP Name 可重名或变更 | 名称是资源、光衰、详情和扩展的 fallback | 旧名称、同名 AP 和硬件替换可能误关联 |
| AP MAC 可能重复或语义混用 | 当前 LLDP neighbor MAC直接查 AP MAC；名称看似 MAC时也参与 fallback | Radio/BSSID/接口 MAC可能被当 AP MAC |
| 交换机接口被误当 AP 键 | 拓扑合并使用接口，历史恢复也依赖接口 | 端口移动或复用时不能代表同一物理 AP |
| 位置字段被当身份 | 站点/PVID决定候选范围，扩展提供区间/里程 | 同站点、同区间存在多个 AP，不能唯一定位 |
| 历史 LLDP 过期 | 当前 LLDP缺失时沿用旧交换机/接口 | AP 移动端口后可能保留旧拓扑关系 |
| 扩展名称 fallback 无 AC 作用域 | 资源 enrichment 在 MAC 未命中时按名称 | 扩展位置可能附到同名资源 |
| 全量字典覆盖 | 相同 key 后写覆盖前写 | 结果可能依赖查询/迭代顺序 |
| 详情 UUID 快速路径不验证 | AC UUID+AP UUID直接返回 | 过期页面行仍会继续打开后续详情加载 |

必须持续保持：交换机接口不是 AP identity；站点、区间、里程不能单独确定 AP；Radio/BSSID/Peer MAC 不能强行等同 AP MAC。

## 7. AP identity 工具可接入点

| 接入点 | Observation 输入 | Candidate 来源 | 建议 shadow 输出 | 风险和回滚 |
| --- | --- | --- | --- | --- |
| 轨旁聚合完成后 | 行内 AP UUID/MAC/name/AC UUID、serial、site；交换机 UUID/interface 只作 topology evidence | 当次完整 FIT-AP 资源 | old/new 状态、候选、identity_changed、missing scope、interface-only、LLDP evidence | 最适合作为阶段 4.1 主入口；只附加摘要，删除字段即可回滚 |
| AP 详情解析前 | 页面提交的 AC UUID、AP UUID、MAC、name | handler 已读取的全量 FIT-AP 资源 | old matches 与 resolver result 对比、多候选和证据 | 不得替换 `matches`；shadow 失败不得影响详情终态 |
| 双击定位前 | 当前分页行和行来源字段 | 不新增数据库读取；复用聚合 shadow | 轻量诊断日志或引用行 shadow | UI 时序敏感，阶段 4.1 不建议先改页面 |
| 单 AP 更新范围确定后 | 目标 AP 字段、当前轨旁行、历史 LLDP | FIT-AP 资源 | 选中交换机范围与 resolver AP 的一致性 | 不得改变采集目标；建议后续阶段再做 |
| 导出前 | 完整轨旁行、资源、历史 | 导出进程已有资源 | 诊断 sheet/日志摘要 | 会改变导出结构；阶段 4.1 不接入 |
| 历史查询旁路 | AP UUID/MAC/name 或 switch UUID/interface | 当前资源和历史 snapshot | 当前/历史 identity 差异 | 历史语义复杂，阶段 4.1 不接入 |

## 8. 不建议立即替换的范围

阶段 4.1 仍不得替换：

- `is_trackside_ap_interface()` 的描述/PVID候选端口规则。
- 当前 LLDP、历史 LLDP和光衰邻居接口 fallback。
- `ap_identity_key()`、现有索引、行去重和 topology merge。
- AP 在线/离线、交换机离线、无光、阈值和状态优先级。
- 单 AP/站点光衰采集范围。
- `trackside_fit_ap_detail_resolve` 的原 `matches`。
- 页面双击、选择框、详情窗口和等待时序。
- `trackside_rows`、`trackside_ap_view_cache`、离线 JSON cache。
- 页面列、导出字段、历史表、Repository SQL和数据库 schema。
- MR/Mesh、无线扫描、Online MR 和 Vehicle MR lookup。

发现的误匹配、过期缓存或测试超时只先记录，不在 identity 接入阶段顺手修复。

## 9. 阶段 4.1 只读 shadow 接入

阶段 4.1 已按本节边界完成。实现位于 `services/rail_transit/trackside_ap_identity_shadow.py`，旧聚合器、旧 detail matches、页面、缓存和业务规则保持不变。

### 9.1 适配器边界

当前新增纯 Python `services/rail_transit/trackside_ap_identity_shadow.py`：

```text
TracksideApIdentityShadowService
  - build_observation_from_trackside_row(row)
  - build_candidates_from_fit_ap_resources(resource_rows)
  - shadow_rows(rows, resource_rows)
  - shadow_detail_matches(old_matches, resource_rows, request)
  - summarize_report(items)
```

适配器只接收普通 Mapping，不导入 UI、Repository、Worker、Qt，不写数据库，不执行采集，也不计算轨旁状态。

### 9.2 第一批接入点

阶段 4.1 只接入两个旁路点：

1. `load_trackside_ap_business_snapshot()` 和 `ac_trackside_business_refresh` 在旧聚合完成后，对相同 rows/resources 生成 `identity_shadow`；原 rows 原样返回。
2. `trackside_fit_ap_detail_resolve` 在旧 `matches` 已生成后附加 `detail_identity_shadow`；原 matches、UUID快速路径、MAC/name fallback、无匹配和多匹配选择行为保持不变。

主页面当前使用 dataclass result，兼容 Job 使用 dict result。两条路径应复用同一 adapter，但分别附加可选诊断字段，不能为了统一返回结构重构加载线程。

### 9.3 建议报告字段

```text
available
total
matched
unresolved
ambiguous
identity_unchanged
identity_changed
missing_ac_scope
name_only_matches
lldp_mac_only
interface_only_records
historical_lldp_records
items[]:
  trackside_ref
  topology_key
  old_ap_key
  old_match_source
  new_status
  new_candidate_key
  evidence
  warnings
```

报告不得写入 `trackside_ap_view_cache`、FIT-AP 主表或历史表。shadow 异常统一 `available=false`，旧加载/详情任务继续成功。页面不读取或展示 shadow，因此排序、筛选、分页、双击和导出字段不受影响。

## 10. 测试策略

阶段 4.1 已建立以下回归：

1. 删除 `identity_shadow` 后，轨旁聚合 rows 与当前 golden rows 完全一致。
2. AP UUID、MAC、name-only、跨 AC 重复、同名、无候选、多候选。
3. 当前 LLDP MAC、历史 LLDP、光衰邻居接口、离线台账和 interface-only。
4. Radio/BSSID/Peer MAC 不作为 AP 写入匹配。
5. topology key 始终是 switch UUID/name + normalized interface，不被 AP resolver 覆盖。
6. AP 在线/离线、交换机无光、阈值和导出结果不变。
7. MAC/名称双击仍打开旧 resolver 选中的详情；无匹配和多匹配行为不变。
8. shadow 失败不改变加载或详情 finished/failed 终态。
9. 主页面线程结果与兼容 Job 都包含等价摘要。
10. Qt 双击用例继续独立进程验证；完整 AC UI 套件的共享生命周期问题单独治理。

## 11. 回滚策略

阶段 4.1 的回滚必须是删除或关闭附加 shadow：

- 保留 `build_trackside_ap_business_rows()` 原返回行。
- 保留 `trackside_fit_ap_detail_resolve` 原 `matches`。
- 不迁移、不删除任何旧 helper 或 fallback。
- 不写 shadow 缓存或数据库，因此无需数据回滚。
- adapter import 或运行失败时返回 unavailable，不影响用户流程。

阶段 4.1 已满足上述回滚边界。后续在真实局点观察 shadow 统计前，不进入轨旁生产 resolver 接管；下一阶段只评估 MR/Mesh resolver shadow。
