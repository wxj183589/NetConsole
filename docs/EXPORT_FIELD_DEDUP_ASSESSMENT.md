# 导出字段去重诊断评估

## 1. 背景与范围

本文对应 AP identity 阶段 6。目标是盘点 MR/Mesh、Online MR、Vehicle MR、轨旁 AP、AC/FIT-AP、OmniPeek 和无线扫描导出中的 AP、Peer、Radio、BSSID 字段，设计阶段 6.1 的只读 diagnostics 接入点。

本阶段只更新文档。没有修改导出字段、Excel/CSV 表头、报告 SQL、解析逻辑、数据库 schema、页面展示、列宽、样式或 WPS/Excel 本地打开兼容逻辑，也没有让 `services/ap_identity` 接管任何导出结果。

## 2. 当前导出入口清单

| 导出 | 当前入口与任务 | 数据来源与写出器 | 独立 Export Process | 格式 | 当前测试锁定 | AP identity 字段 |
| --- | --- | --- | --- | --- | --- | --- |
| MR 原始 MESH 链路明细 | `MeshLogAnalysisPage.export_link_details()` → `ExportJob(job_type="mesh_link_detail")` | `MeshMrRepository.iter_link_details()`、主链路建链顺序和事件表 → `export_mesh_link_details_xlsx()` | 是，`export_worker.py` 专用 handler | XLSX | `test_mesh_link_detail_export_writes_xlsx_with_centered_content` 锁定 Sheet、表头、样式、列宽、临时文件清理 | Peer MAC、对端 AP MAC/名称、站点/区间/类型、对端射频口、主链路与 RSSI/Busy |
| MR 原始 MESH 分析报告 | `MeshLogAnalysisPage.generate_report()` → `MeshAnalysisReportWorker` | detail DB → `MeshAnalysisReportService` → `MeshAnalysisExcelReportExporter` | 否；现状是专用 `spawn` 子进程，批量时内部 `ProcessPoolExecutor` | XLSX | `test_excel_report_contains_required_sheets_headers_and_empty_parse_issue_text` 等锁定 Sheet、表头、枚举翻译和取消清理 | Peer/AP/Radio、Active/Standby、备链、RSSI、Busy、短链和乒乓 |
| Online MR 当前页面分析报告 | `OnlineMrCollectionPage.export_analysis_report()` → `online_mr_report_xlsx_spec` | `parsed/online_diagnosis.sqlite` → `VehicleMrOfflineExcelReportExporter` | 是，通用 Export Process | XLSX | 页面导出、默认诊断 Sheet 顺序和空状态测试 | 默认报告含 Peer 名称/MAC、站点/区间、Active/备链和 RSSI；默认不展开 Mesh 采样明细 |
| Online MR 兼容/直接详细报告 | `OnlineMrAnalysisReportExporter.export()`；当前页面未调用 | parsed DB + `OnlineMrChartBuilder`，直接查询并生成详细 Sheet/图表 | 直接调用时否；不是当前页面 ExportJob formatter | XLSX | `test_online_mr_chart_builder_active_rssi_switch_empty_link_and_export` 锁定核心 Sheet 集合 | 详细 Sheet 同时包含 PeerMac、AP MAC、Peer Radio MAC、BSSID 和归属来源 |
| Vehicle MR 历史记录 | `VehicleMrOnlinePage.export()` → `vehicle_mr_history_xlsx_spec` | `VehicleMrOnlineStore.query_events()` → `export_vehicle_mr_history_xlsx()` | 是 | XLSX | `test_vehicle_mr_history_export_writes_rows` 锁定基础表头和行值 | 轨旁 AP 名称、站点和 RSSI；没有 AP/Radio MAC |
| Vehicle MR 映射模板 | `VehicleMrOnlinePage.export_template()` → `table_xlsx_spec` | 固定小模板 rows → 通用 table exporter | 是 | XLSX | `test_mapping_template_export_contains_required_headers` | TC1/TC2 Peer Name；属于配置模板，不是 identity 解析结果 |
| 轨旁 AP 业务 | `TracksideApServicePage.export_trackside_table()`/兼容 AC 页面 → `ExportJob(job_type="trackside_ap_business")` | 站点 DB 的设备事实、FIT-AP、光衰、LLDP、在线概览和离线台账 → `export_trackside_ap_business_xlsx()` | 是，`export_worker.py` 专用 handler | XLSX | 多个测试锁定 Sheet 顺序、主表字段、异常光衰筛选、样式、列宽和内部字段排除 | AP MAC/名称、站点、交换机接口、光衰；“新增上线 AP 概览”另含 identity source |
| AC FIT-AP 光衰 | `AcManagementPage.export_optical_table()` → `fit_ap_optical_xlsx_spec` | FIT-AP 光衰 + 资源 + AP 在线概览 → `export_fit_ap_optical_xlsx()` | 是 | XLSX | `test_export_fit_ap_optical_xlsx_contains_overview_and_optical_sheets` 锁定两个 Sheet、表头、状态、颜色和列宽 | AP 名称/MAC、站点、交换机/接口和两侧光衰；无 Peer/Radio/BSSID |
| AC FIT-AP 资源 | `AcManagementPage.export_aps()` → `fit_ap_csv_spec` | `AcRepository.list_fit_ap_resources_with_metadata()` → `FitApImportExportService.export_ap_csv()` | 是 | UTF-8-SIG CSV | `test_import_and_export_fit_ap_metadata` 锁定字段存在、顺序和明确排除 BSSID/RID3 | AP 名称/MAC、APID、IP、RID1/2 参数、站点/区间/类型/里程 |
| FIT-AP 扩展信息/模板 | `export_ap_extensions()`/`export_ap_extension_template()` | AP 扩展表、FIT-AP 和 `ap_entities` → `FitApImportExportService` | 是 | XLSX | 模板字段、可编辑字段、空模板和页面提交测试 | AP 名称/MAC、站点/区间/里程；属于工程属性和绑定信息 |
| AP 在线概览 | `AcManagementPage.export_overview_table()` → `ap_online_overview_xlsx_spec` | FIT-AP、光衰、metadata、容量和离线台账 | 是 | XLSX | 概览颜色、对齐、离线台账和跨页面一致性测试 | 聚合站点数量；离线台账含 AP 名称/MAC |
| OmniPeek 名称表 | AC 页面 preview Job → `omnipeek_name_table_spec` | FIT-AP、AP 扩展、设备管理车载 MR → `OmniPeekNameTableService` | 是 | UTF-8 XML `.nam` + 日志 | `test_omnipeek_name_table.py` 锁定名称、物理/R1/R2 MAC 推导和 XML 字段 | 物理 MAC 与派生 R1/R2 MAC；这是目标格式要求，不属于重复展示列 |
| 无线扫描（邻接入口） | `WirelessScanPage.export_current()` → repository-backed table export | 无线扫描库中原始 BSSID 与轨旁 resolver 展示结果 | 是 | XLSX/CSV | `test_wireless_scan.py` 锁定显示/导出列一致及字段顺序 | 原始 BSSID（“MAC地址”）、映射 AP MAC/名称、射频口、站点/区间/归属来源 |

仓库没有二进制 `.xlsx` golden fixture。现有“golden”含义是结构化契约测试：读取生成文件并断言 Sheet、表头、关键行值、样式、列宽、筛选、冻结窗格和临时文件清理。阶段 6.1 应延续这种逻辑 golden，而不是比较不稳定的 XLSX 二进制哈希。

## 3. AP、Peer、Radio 和 BSSID 字段矩阵

| 字段 | 当前语义和来源 | 可能重复/为空 | 是否参与匹配 | 导出边界 |
| --- | --- | --- | --- | --- |
| Peer MAC | MR/Mesh 原始日志观测；Online MR 来自 `main_link_samples.peer_mac` | 可为空；可能与显式 Peer Radio MAC 或映射后的 AP MAC 同值 | 生产 mapping 可把它作为 observation，但不能默认解释为 AP MAC | 原始证据字段，不自动删除或改值 |
| Peer Radio MAC | mapping/cache 中对 Peer Radio/BSSID 的显式或 H3C 派生结果 | 常与 Peer MAC 相同；Online 兼容详细报告当前直接重复使用 `peer_mac` | 只有候选显式具备 Radio/BSSID 映射时才可支持匹配 | Mesh 链路明细已移除；其他入口只诊断，不自动去重 |
| Peer Name | 原始 Peer Name，或 mapping 后的 resolved name | 可为空、可为 MAC-like、可与 AP Name 相同 | 名称只按作用域和唯一性作低置信证据 | 保留原始/解析语义，不用名称覆盖 MAC |
| AP MAC | FIT-AP 主资源字段，或 Mesh/轨旁 resolver 的 AP 映射结果 | 可为空；可能与 Peer MAC 同值；Online 兼容详细报告目前并非真实 AP MAC，而是再次选择 `peer_mac` | 上游生产 resolver 已使用；导出层只展示 | 不从 Peer/Radio/BSSID 自动生成或回写 |
| AP Name | FIT-AP/扩展/轨旁映射结果 | 可为空、重名或 MAC-like；Vehicle MR 常只有名称 | 可作为带作用域的降级证据 | name-only 和 MAC-like 只做诊断 |
| Radio MAC | FIT-AP 显式 Radio 资源或 H3C 规则派生 | 可与 BSSID/Peer MAC 同值 | 只在显式 Radio mapping 下参与 | 核心 Mesh 明细以“对端射频口”展示，不新增 Radio MAC 列 |
| BSSID/BBSSID | 无线扫描原始观测，或 FIT-AP Radio 资源 | 可为空；可能与 Radio MAC/Peer MAC 同值 | 只作为 Radio observation | 无线扫描必须保留原始 BSSID；FIT-AP 资源 CSV 已明确不导出 BSSID |
| 归属来源/identity source | resolver/mapping 的来源说明，不是 AP identity | 不同导出存在性不同；可为空 | 不参与 identity 决策 | 只诊断存在性，不能强行统一列 |
| 归属站点/区间/里程 | AP 扩展、metadata 或 mapping 的位置字段 | section 可有值而 station 为空 | 仅辅助 evidence，不消歧 | 保留各导出当前名称和空值语义 |
| 主链路/备份链路 | 原始 `link_state` 及派生 Active/Standby/Backup 上下文 | 备链可能缺失，但不是字段重复问题 | 参与链路质量、区段、切换和风险判断 | 绝不因 MAC 去重修改 |
| 最低 RSSI | 对 Active/Peer/区段采样的聚合值 | 数据缺失或聚合上下文不足时可为空 | 不参与 identity 匹配 | 只做完整性诊断，不重算、不补值 |
| TxBusy/RxBusy | 原始采样或聚合指标 | 可为空；本地/对端/最大值是不同语义 | 不参与 identity 匹配 | 不因列名相近自动合并 |

## 4. 当前导出字段差异

1. Mesh 链路明细保留 `Peer MAC`、`对端AP MAC`、`对端AP名称`、归属信息和`对端射频口`，已经移除“归属来源”和“Peer Radio MAC”。
2. MR 原始 MESH 分析报告仍在不同 Sheet 中保留 Peer、AP、Radio、Active、备链、RSSI 和 Busy 的业务语义；这些不是可机械去重的平铺列。
3. Online MR 当前页面默认报告不展开大体量 Mesh 明细；兼容/直接 `OnlineMrAnalysisReportExporter` 仍包含详细“链路明细”。
4. 兼容/直接 Online MR“链路明细”的 SQL 将同一个 `peer_mac` 同时填入 `PeerMac`、`AP MAC`、`Peer Radio MAC`，属于明确的重复展示风险；本阶段只记录，不修改 SQL或表头。
5. Online MR 兼容报告的“Mesh主链路质量”保留“归属来源”，与 Mesh 链路明细的既有移除策略不同。两者用途不同，不能自动统一。
6. 轨旁 AP 业务主表不导出内部 match source，但“新增上线 AP 概览”保留 identity source；这是 Sheet 语义差异。
7. FIT-AP 资源 CSV 保留 RID1/RID2 信道、频宽和功率，不导出 BSSID；OmniPeek 则有意导出物理/R1/R2 三类 MAC。
8. 无线扫描同时展示原始 BSSID、映射 AP MAC 和射频口，三者属于观察层、AP identity 层和 Radio 层，不能折叠。

## 5. 已知要求和保护约束

- Mesh 链路明细不需要“归属来源”。
- Peer Radio MAC 与 Peer MAC 重复时不应在 Mesh 链路明细重复展示；当前表头已移除 Peer Radio MAC。
- Online MR 兼容报告存在 PeerMac、AP MAC、Peer Radio MAC 同值风险，但当前页面入口和兼容直接服务必须分开评估。
- Online MR 主链路兼容报告仍包含“归属来源”，本阶段不移除。
- “全无备份链路”曾是错误现象；任何字段诊断不得改变 ACTIVE/STANDBY、备链数量或备链判定 SQL/模型。
- 大量最低 RSSI 空值曾是风险；diagnostics 只能统计缺失，不得补值或修改聚合。
- 短时建链、同 AP 双 Radio、乒乓、主链路顺序、RSSI、TxBusy/RxBusy 继续由现有分析规则决定。
- XLSX 自动列宽、筛选、冻结窗格、颜色、临时文件替换和 WPS/Excel 本地打开兼容必须保持现状；不引入 WPS 云服务、API 或在线同步。
- 原始 H3C 回显、raw log 和 parser 输出必须完整保留，diagnostics 不参与解析。

## 6. 重复字段和语义冲突风险

| 风险 | 典型入口 | 安全处理 |
| --- | --- | --- |
| Peer MAC = Peer Radio MAC | 离线 Mesh mapping/cache、Online 兼容明细 | 计数并保留样例引用；不改原始值 |
| Peer MAC = AP MAC | 映射数据或 Online 兼容明细 | 标记语义冲突；不推断二者等价 |
| 三个 MAC 列来自同一 SQL字段 | Online 兼容详细报告 | 高优先级诊断；不修改 SQL/表头 |
| AP Name 是 MAC-like | Vehicle MR、扩展信息、旧 mapping | 记录 name-only/MAC-like；不自动改名 |
| Radio/BSSID-only | 无线扫描、缺少 AP identity 的 Mesh observation | 保持 observation；没有显式 mapping 时 unresolved |
| 缺少 AC scope | 跨 AC 的 FIT-AP、Mesh/Vehicle 名称匹配 | 记录 missing scope；不静默选第一条 |
| “归属来源”存在性不一致 | Mesh、Online、轨旁、无线扫描 | 按导出用途记录，不统一表头 |
| 最低 RSSI为空 | MR/Online 分析报告 | 只统计完整性，不补值、不重算 |
| 备链上下文缺失 | MR/Online 分析报告 | 只统计缺失上下文，不改变备链结论 |

## 7. 可诊断字段与不可自动去重字段

可安全诊断：

- Peer MAC 与 Peer Radio MAC 相同。
- Peer MAC 与 AP MAC 相同。
- AP Name/Peer Name 是 MAC-like。
- Radio/BSSID-only 记录。
- 缺少 AC scope、name-only 记录。
- “归属来源”字段在目标导出是否存在、是否为空。
- 最低 RSSI 和备链上下文的缺失数量；仅作为完整性指标。

不可自动去重或改写：

- 原始日志 Peer MAC、Peer Radio MAC、BSSID/BBSSID。
- 映射结果 AP MAC、AP Name、Radio label/MAC。
- 主链路/备份链路、Active/Standby、主链路顺序。
- RSSI、min RSSI、TxBusy/RxBusy 和聚合结果。
- 轨旁拓扑字段、光衰状态和异常 Sheet。
- OmniPeek 物理/R1/R2 MAC；它们是目标格式中的不同 entry kind。
- 已被现有报表、现场模板或测试依赖的表头、Sheet 和行值。

## 8. 阶段 6.1 只读 diagnostics 接入方案

统一建议模型为 `ExportIdentityDiagnostics`，只包含聚合计数、最多 50 条脱敏/最小样例引用和 warnings：

```text
available
export_type
total
sampled
peer_mac_equals_peer_radio_mac
peer_mac_equals_ap_mac
mac_like_names
radio_or_bssid_only_records
missing_ac_scope
name_only_records
belonging_source_present
belonging_source_missing
missing_min_rssi_records
missing_backup_context_records
warnings
samples
```

| 推荐接入点 | 输入 | 可诊断字段 | workbook/result/sidecar | 风险与回滚 | 测试要求 |
| --- | --- | --- | --- | --- | --- |
| P0：Mesh 链路明细写出前 | Export Process 已查询的 link rows 和 mapping 字段 | Peer/AP/Radio 重复、MAC-like、scope、归属来源存在性、RSSI缺失 | workbook 零变化；finished result 可选增加小型 diagnostics；sidecar 默认关闭 | 大数据只能流式计数并限制样例；删除 wrapper 即回滚 | 现有 Sheet/表头/行值/样式/列宽逻辑 golden 完全一致，取消仍单终态 |
| P0：Online MR 兼容详细报告写出前 | 现有 `_mesh_link_detail_rows()` 返回值 | 三个 MAC 列同源、BSSID-only、归属来源差异 | 不改 SQL和 worksheet；建议先仅返回 diagnostics，不写 sidecar | 当前 rows 是位置数组，字段错位风险高；删除诊断调用即回滚 | 明确断言三列风险被统计，同时旧 workbook 逻辑值不变 |
| P1：MR 原始 MESH 分析报告模型完成后 | `MeshAnalysisReportModel` 各 Sheet rows | Peer/AP字段、备链上下文、min RSSI完整性 | 不改 model/Sheet；可写运行缓存 sidecar，默认不随报告分发 | 多 Sheet 重复计数和大数据成本；按 record_ref 去重 | Sheet顺序、字段、评分、短链/乒乓和枚举翻译保持一致 |
| P1：Online MR 当前页面报告生成前 | 当前 exporter 已生成的默认报告 rows | Peer/name、scope、站点/区间、min RSSI/备链完整性 | 不新增报告 SQL；现有 rows 不暴露字段时标记 unavailable；不改 workbook/result | 为诊断扩大 SQL 会越界；删除诊断适配即回滚 | 当前默认 Sheet 顺序和空状态完全一致 |
| P1：Vehicle MR 历史/模板导出前 | history rows 或 mapping template rows | name-only、MAC-like name、scope缺失 | workbook 零变化；无必要默认 sidecar | 数据没有 AP MAC，禁止调用带写副作用 lookup；删除调用回滚 | 原表头和行值完全一致，Candidate unavailable 不影响导出 |
| P1：轨旁 AP 业务 workbook 生成前 | 已完成旧聚合的 export rows | AP name/MAC缺失或冲突、identity source存在性 | 不改主表/异常Sheet/结果；可在 Export Job result 附加汇总 | 不能改变光衰、离线台账和 topology 关联；删除调用回滚 | 现有多 Sheet、异常筛选、颜色、列宽和内部字段排除全部通过 |
| P2：AC 光衰/FIT-AP/OmniPeek/无线扫描 | 各 exporter 已有 rows/items | AP name/MAC、派生 Radio/BSSID、scope和冲突 | 不改 CSV/XLSX/NAM；默认只返回诊断 | OmniPeek 已有专用冲突规则，不重复接管；删除调用回滚 | 现有表头、XML entry、派生 MAC和样式契约不变 |

阶段 6.1 不应新增报告 SQL。若现有 formatter 输入没有足够字段，diagnostics 必须返回 `available=false`，不能为了统计改 parser、Repository、查询、workbook 或页面。

## 9. 测试策略

1. 新增纯 Python diagnostics service 测试，不导入 UI、Workbook、Repository 或 parser。
2. 覆盖 Peer/Peer Radio/AP MAC 相同与不同、空值、非法值、MAC-like name、BSSID-only、name-only、missing scope。
3. 覆盖 Online MR 三列同源风险，但不把测试期望改成去重后的表头。
4. 对每个接入点运行逻辑 golden：Sheet 顺序、表头、关键行值、数据类型、筛选、冻结窗格、颜色和列宽保持一致。
5. 保护 ACTIVE/STANDBY、备链数量、主链路顺序、短链、乒乓、min RSSI 和 Busy 统计。
6. diagnostics 异常、无安全字段和取消时，原导出终态、临时文件清理和输出替换行为不变。
7. sidecar 如后续启用，应使用 UTF-8 JSON、原子替换、有限样例且不包含现场凭据；sidecar 失败不得使原导出失败。

## 10. 回滚和准入结论

- 阶段 6 本身只有文档，删除本轮文档增量即可回滚。
- 阶段 6.1 只能以可删除的只读 adapter/wrapper 接入；旧 formatter、SQL、表头和 Export Job 必须保留。
- 当前可以进入阶段 6.1，但只建议先做 P0 的纯 diagnostics service 和两个 MR/Mesh 接入点。
- 在真实局点统计稳定、逻辑 golden 完全一致之前，不进入导出字段删除、改名、合并或 SQL修复阶段。

## 11. 阶段 6.1 P0 实施结果

阶段 6.1 已按本文 P0 边界完成：

- 新增纯 Python `services/export_identity_diagnostics.py`，只读取普通 mapping/位置数组，流式统计重复 MAC、MAC-like 名称、Radio/BSSID-only、缺失字段和字段存在性；不导入 UI、Repository、Workbook、SQLite 或 parser。
- Mesh 链路明细在每个旧 row 进入 `link_detail_row_values()` 前旁路统计，`export_worker` 仅在 finished result 中附加 `export_identity_diagnostics`。现有 Sheet、表头、行值、样式、列宽、筛选、冻结窗格和临时文件替换不变。
- `OnlineMrAnalysisReportExporter` 在既有 `_mesh_link_detail_rows()` 返回后、worksheet 写入前按原表头解释位置数组，并通过 `result_metadata` 暴露 `export_identity_diagnostics`。原 SQL、三列同源值、Sheet 和 workbook 返回类型不变。
- diagnostics 初始化、逐行统计或汇总失败时统一降级为 `available=false`；原导出继续完成。默认不生成 sidecar，也不写数据库或运行缓存。
- 当前观察结果只能说明字段相同或上下文缺失，不能授权删除、改名、合并字段，也不能改变 AP/Radio/Peer identity、ACTIVE/STANDBY、备链、RSSI、Busy、短链或乒乓结论。

阶段 7 已完成真实局点 diagnostics 观测、脱敏汇总、准入阈值和运行手册设计，见 [AP_IDENTITY_OBSERVATION_PLAN.md](AP_IDENTITY_OBSERVATION_PLAN.md)。在获得稳定脱敏样本前，仍不得修改导出字段或报告 SQL；即使达到初始阈值，也只能进入只读展示评估。

阶段 8 只读展示评估见 [AP_IDENTITY_DISPLAY_ASSESSMENT.md](AP_IDENTITY_DISPLAY_ASSESSMENT.md)。阶段 8.1 优先只读消费现有 metadata，不改 workbook、不新增默认 sidecar，也不展示 `samples/warnings/error`；报告 Sheet、首页摘要和独立 XLSX 均不进入最小实现。
