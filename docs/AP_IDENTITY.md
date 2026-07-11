# AP Identity 工具

## 1. 工具定位

`netconsole/services/ap_identity/` 是 AP 统一模型阶段 1 的纯 Python、只读 identity 工具。它把 AP、Radio、BSSID/BBSSID、Peer observation、位置和拓扑作用域分开表达，并返回可审计的匹配证据。

当前阶段只供单元测试和后续适配设计使用，尚未接入 AC、光衰、轨旁、MR/Mesh、无线扫描、Repository、页面、Job Center 或导出流程。

目录结构：

```text
netconsole/services/ap_identity/
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

本阶段不修改数据库 schema、生产写入语义、页面字段、导出表头或现有业务测试期望。

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
| 7 | 显式 `radio_mac` 或 `bssid/bbssid` | 90 |
| 8 | Peer observation 命中显式 Radio/BSSID | 80 |
| 证据 | Peer observation 只命中 AP MAC | 55，不产生 matched |
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

适配器只复制和转换 Mapping，不导入 Repository、UI、Worker、Netmiko，不访问数据库或网络。当前生产模块尚未调用这些函数。

## 10. 后续接入与回滚

下一阶段只评估 AC FIT-AP 与 AP 扩展信息共用 identity 适配：

1. 先对旧 helper 与新工具做 shadow comparison。
2. 比较 matched、unresolved、ambiguous、UUID/MAC/name 变化数量。
3. 保持 Repository SQL、schema、返回字段和业务规则不变。
4. 通过具名兼容适配器切换；出现非预期差异时直接回退旧 helper。

阶段 2 完成并单独验收前，不接入光衰、轨旁、MR/Mesh、无线扫描或导出。
