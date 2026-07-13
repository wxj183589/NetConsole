# AP Identity 工具

## 1. 工具定位

`src/netconsole/services/ap_identity/` 是 AP 统一模型阶段 1 的纯 Python、只读 identity 工具。它把 AP、Radio、BSSID/BBSSID、Peer observation、位置和拓扑作用域分开表达，并返回可审计的匹配证据。

阶段 2 已在 AC FIT-AP 资源与 AP 扩展信息之间接入只读 shadow comparison；阶段 3 已在 AC 光衰 Job result 中附加只读 `identity_shadow`；阶段 4/4.1 已完成轨旁评估和只读 shadow 接入；阶段 5/5.1 已完成 MR/Mesh评估和第一批只读shadow接入；阶段 6/6.1 已完成导出评估和两个 P0 diagnostics 接入；阶段 7 已定义真实局点只读观测、脱敏汇总和准入阈值；阶段 8 已完成只读展示方案评估；阶段 8.1 已实现默认关闭的纯 Python 诊断摘要 ViewModel；阶段 8.2 已确认当前没有统一 Job 详情宿主，阶段 8.3 可见 UI 暂缓。各阶段均未让 resolver 接管生产结果；MR/Mesh生产解析、无线扫描、页面和导出字段语义保持不变。

目录结构：

```text
src/netconsole/services/ap_identity/
  __init__.py       # 稳定导出面
  models.py         # frozen dataclass 与匹配状态
  normalizers.py    # MAC、名称、里程和线别纯函数
  resolver.py       # 保守只读 resolver
  adapters.py       # dict/row 到 Candidate/Observation 的只读转换
```

## 2. 非目标

本工具不是：

- 新 AP 主表、宽表或 Repository。
- `ap_entities` 的替代品。
- 数据库写入、网络采集、Worker 或 UI 服务。
- 光衰异常、在线/离线、轨旁规划或 MR/Mesh 分析规则引擎。
- “尽量匹配”的模糊绑定器。

阶段 1/2 均不修改数据库 schema、生产写入语义、页面字段、导出表头或现有业务测试期望。

## 3. 模型定义

### 3.1 Identity

`CanonicalApIdentity` 表达物理 AP 候选：

- `ap_uuid`：站点数据库内已解析 UUID。
- `ap_mac`：物理 AP MAC。
- `ap_name`：AP 名称，允许为 MAC-like 原文。
- `ac_uuid + ap_id`：AC 作用域内运行态 APID。
- `serial_number`、`site_id`：可选身份上下文。
- `source/source_ref`：来源和可追溯引用。

SQLite 行 `id` 只进入 `source_ref/raw`，不参与 identity 匹配。

### 3.2 Radio/BSSID

`CanonicalApRadioIdentity` 是 AP 子实体，包含 `radio_id`、`radio_mac`、`bssid`、`bbssid` 和 band。Radio/BSSID 不会写入 `CanonicalApIdentity.ap_mac`。

阶段 1 resolver 只接受 Candidate 中显式存在的 Radio/BSSID 映射，不根据 AP MAC 自动推导 H3C Radio 1/2。后续如复用现有 H3C 映射规则，应由阶段 2 之后的具名适配器生成 Radio Candidate，并用 shadow comparison 验证。

### 3.3 Location 与拓扑上下文

`CanonicalApLocation` 分开保存 site、station、section、mileage、line、direction、ownership、system type 和 network domain。

`ApObservation` 保留 `ac_uuid`、`device_uuid`、`interface_name` 和 source reference。它可以描述交换机接口或日志样本的作用域，但这些字段不会单独确定 AP。

### 3.4 Observation、Candidate、Evidence

- `ApObservation`：一次查询、日志或扫描观测；Peer MAC 只存在于 observation。
- `ApIdentityCandidate`：只读 AP identity、Radio 列表、位置和 raw 快照。
- `ApMatchEvidence`：参与匹配或辅助说明的字段、双方值、置信度和原因。
- `ApMatchResult`：`matched/unresolved/ambiguous`、候选、证据和 warnings。

所有模型使用 frozen dataclass；raw 映射复制后以只读 Mapping 暴露，适配器不修改输入 row。

## 4. 规范化规则

### 4.1 MAC

支持：

```text
aa:bb:cc:dd:ee:ff
AA-BB-CC-DD-EE-FF
aabb.ccdd.eeff
aabbccddeeff
```

统一输出小写冒号格式：`aa:bb:cc:dd:ee:ff`。

空值、`N/A`、`--`、`unknown`、`None` 和非法 MAC 返回 `None`；不会删除任意非十六进制字符后强行拼成 MAC。

### 4.2 AP 名称

名称只去除首尾空格并折叠连续空白，保留大小写和原始语义。名称即使是 MAC-like，也只通过 `is_mac_like()` 提供证据，不会自动覆盖 `ap_mac`。

### 4.3 里程与线别

复用现有 `utils.mileage` 解析，识别并规范化：

- `!Z!D!K##+###` → 左线/下行。
- `!Y!D!K##+###` → 右线/上行。
- `!C!D!K##+###` → 出段线/出段。
- `!R!D!K##+###` → 入段线/入段。

identity 工具只识别和规范化，不改变里程业务含义。

## 5. 匹配优先级

Resolver 使用第一个有候选的精确策略，不用位置字段给重复 identity 强行消歧：

| 顺序 | 规则 | 置信度 |
| ---: | --- | ---: |
| 1 | `ap_uuid` 精确 | 100 |
| 2 | `ac_uuid + ap_id/apid` 精确 | 98 |
| 3 | `ac_uuid + ap_mac` 精确 | 96 |
| 4 | `ap_mac` 精确 | 92 |
| 5 | `ac_uuid + ap_name` 精确 | 85 |
| 6 | `ap_name` 精确 | 75 |
| 7 | 显式 `radio_mac` | 90 |
| 8 | 显式 `bssid/bbssid` | 90 |
| 9 | `peer_radio_mac`，再以 `peer_mac` 命中显式 Radio/BSSID | 80 |
| 10（证据） | Peer observation 只命中 AP MAC | 55，不产生 matched |
| 辅助 | site/station/section/mileage 一致 | 10，只追加证据 |

AP MAC 优先于 AP 名称。相同 AP MAC/名称跨 AC 重复时，无 AC 作用域返回 ambiguous；不会选择第一条。

## 6. matched、ambiguous 与 unresolved

- `matched`：当前精确策略只有一个候选。
- `ambiguous`：当前最高优先级有效策略得到多个候选。
- `unresolved`：没有可靠候选，或 Peer 只低置信命中 AP MAC但缺少显式映射。

位置字段、站点、区间、里程和交换机接口只能补充证据，不能单独将 unresolved 变为 matched。

## 7. Radio、BSSID 与 Peer 边界

- Radio MAC、BSSID、BBSSID 是射频/BSS 身份，不是物理 AP MAC。
- `peer_mac` 和 `peer_radio_mac` 永远先作为 observation。
- Peer 命中显式 Candidate Radio/BSSID 时可 matched。
- Peer 只命中 Candidate AP MAC 时返回低置信 Evidence 和 unresolved warning。
- `peer_mac` 与 `peer_radio_mac` 规范化后相同时，保留两个原始字段，并添加重复 warning；本阶段不修改导出展示。

## 8. 位置和业务边界

- section 可以存在而 station 为空，两者不互相覆盖。
- PIS 不自动生成红/蓝网络域；信号系统只保留来源明确提供的 network domain。
- 轨旁规划不是 AP identity 真源。
- 光衰 observation 应保留 AC、AP、交换机 device/interface 上下文，但本工具不计算异常。
- “交换机无光但 AP 未离线不直接异常”等规则继续由原业务服务负责。

## 9. 只读适配器

当前提供：

- `candidate_from_ap_entity_row()`
- `candidate_from_fit_ap_resource_row()`
- `candidate_from_extension_row()`
- `observation_from_mesh_peer()`
- `observation_from_online_mr_sample()`
- `observation_from_wireless_bssid()`

适配器只复制和转换 Mapping，不导入 Repository、UI、Worker、Netmiko，不访问数据库或网络。阶段 2 仅由 `services/ac/ac_identity_adapter.py` 调用，并由 AC handler 在既有 Repository 读取完成后传入普通 row。

## 10. 阶段 2 AC shadow comparison

`AcApIdentityAdapter` 提供：

- FIT-AP row → Candidate。
- 扩展信息 row → Observation。
- 旧 MAC/name helper baseline 与新 resolver 对比。
- `matched/unresolved/ambiguous/identity_changed` 汇总。
- name-only、MAC-like name、缺失 AC 作用域统计。

`identity_changed` 表示旧/new 匹配状态不同，或双方都 matched 但候选 identity 不同；它只用于诊断，不会改变 commit/save 的旧写入 key。

当前接入点：

- `fit_ap_extension_preview`：保留原 preview 字段并附加 shadow。
- `fit_ap_extension_commit`：写入前生成 shadow，之后仍调用 `FitApImportExportService.commit_ap_extension_import()`。
- `ac_ap_extensions_refresh`：保留原 rows 并附加 shadow。
- `ac_ap_extension_save`：写入前生成 shadow，之后仍调用 legacy save helper。

旧 `legacy_tasks` helper 保持不变，是直接回滚路径。shadow 自身异常时返回 `available=false` 和 warning，不阻断旧流程。

## 11. 阶段 3 光衰 identity shadow

`AcOpticalIdentityAdapter` 只接收光衰 row 和 FIT-AP row，并区分 `ap_side/switch_side/merged/offline`：

- AP 侧和已有旧 AP 绑定的记录可与 resolver 候选对比。
- 仅有交换机接口的记录固定 unresolved；交换机接口不是 AP identity。
- Radio MAC、BSSID/BBSSID 和 Peer MAC 只生成语义风险 warning，不进入光衰 AP 匹配。
- AC/FIT-AP 常见 `xxxx-xxxx-xxxx` MAC 只在本适配器边界转换后交给通用 resolver，不改通用模型或持久化值。
- report 统计 matched、unresolved、ambiguous、identity unchanged/changed、记录类型、interface-only、name-only、MAC-like name 和缺失 AC 作用域。

`ac_fit_ap_optical_refresh` 的 load/collect、all/single 都保留原 result 字段，只新增 `identity_shadow`。shadow 异常返回 `available=false`，不改变 finished/failed；删除该附加字段即可回退。原 `AcOpticalService` 的 UUID/name 关联、AP 在线/离线、交换机无光、阈值、历史合并和 Repository 写入仍是生产路径。

## 12. 轨旁、MR/Mesh 与导出后续接入

轨旁业务的数据来源、旧 lookup、双击详情、缓存/历史和阶段 4.1 实现见 [TRACKSIDE_AP_IDENTITY_ASSESSMENT.md](TRACKSIDE_AP_IDENTITY_ASSESSMENT.md)。当前只在旧聚合完成后附加 `identity_shadow`，在旧详情 matches 生成后附加 `detail_identity_shadow`；lookup、缓存、双击定位、采集范围和业务规则均未替换。

MR/Mesh、Online MR、Vehicle MR 的数据来源、Peer/Radio语义、lookup差异、主备链依赖、导出风险和阶段 5.1实现见 [MR_MESH_AP_IDENTITY_ASSESSMENT.md](MR_MESH_AP_IDENTITY_ASSESSMENT.md)。当前只在`mesh_log_import`、`online_mr_parse`和`vehicle_mr_mapping_load`旧结果后附加`identity_shadow`；生产parser、mapping/cache、链路判断、页面和导出未接入shadow。

阶段 6 导出字段去重诊断评估与阶段 6.1 P0 实施见 [EXPORT_FIELD_DEDUP_ASSESSMENT.md](EXPORT_FIELD_DEDUP_ASSESSMENT.md)。Mesh 链路明细和 `OnlineMrAnalysisReportExporter` 只附加小型 `export_identity_diagnostics` 元数据；没有修改 workbook/CSV/NAM、表头、报告 SQL、解析、页面或业务统计，默认不写 sidecar。

阶段 7 真实局点运行步骤、统一指标、HMAC 脱敏、采样范围、风险分级和保守决策门见 [AP_IDENTITY_OBSERVATION_PLAN.md](AP_IDENTITY_OBSERVATION_PLAN.md)。观测只提取聚合，不保存完整 items/evidence/raw log/xlsx；达到阈值也只允许进入阶段 8 的只读展示评估，不授权生产接管。

阶段 8 可展示字段允许列表、禁止字段、UI/报告候选、默认关闭策略、不可用状态和阶段 8.1 实现见 [AP_IDENTITY_DISPLAY_ASSESSMENT.md](AP_IDENTITY_DISPLAY_ASSESSMENT.md)。阶段 8.2 Job/Export 宿主现状、七类结果流、候选矩阵和阶段 8.3 准入结论见 [AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md](AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md)。当前没有统一 Job 详情启动点或安全结果保留层；阶段 8.3 可见 UI 暂缓，不得改业务页面或持久化完整 result。

## 13. 2026-07-11 代码同步结论

- 统一模型仍为 `CanonicalApIdentity`、`CanonicalApRadioIdentity`、`CanonicalApLocation`、`ApObservation`、`ApIdentityCandidate`、`ApMatchEvidence`、`ApMatchResult`。
- resolver 仍按显式 UUID、AC 作用域 ID/MAC、全局 AP MAC、作用域名称/名称、Radio/BSSID、peer observation 的保守顺序解析；唯一候选才 matched，多候选 ambiguous，无候选 unresolved。位置只作辅助证据，不单独决定身份。
- peer 到 AP MAC 的低置信 fallback 仍只形成 unresolved 诊断，不允许伪装成 matched。
- 当前接入仍只附加 `identity_shadow`、`detail_identity_shadow` 或 `export_identity_diagnostics`；没有替换旧 matcher、数据库写入、页面字段或报表统计。
- `online_mr_parse` 可附加 shadow，但 Online MR 实时生产匹配不接管；Mesh 链路明细 diagnostics 只随 finished result 返回 metadata。
- 阶段 8.3 继续 hold。没有真实局点准入结果、统一 Job 详情宿主和安全结果生命周期之前，不新增可见 UI。
