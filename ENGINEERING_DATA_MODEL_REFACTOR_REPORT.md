# Engineering Data Model Refactor Report

日期：2026-08-26

## 范围

本轮同时收口 FIT-AP LLDP 与 AP 光衰数据模型，代码 HEAD 起点为 `e8b826b9b6d3e799fc2bd71afe07ece07b4b2769`，只使用 `D:\NetConsoleData-dev` 验证。

## 目标模型

| 领域 | Current | History | 业务台账 | 身份键 | 保留策略 |
| --- | --- | --- | --- | --- | --- |
| LLDP | `fit_ap_lldp_current` | `fit_ap_lldp_history` | 复用当前 LLDP 关系 | AP Identity / 规范化 MAC + 接口与邻居关系 | 真实变化，单 AP 最多 10 条 |
| Optical | `optical_current` | `optical_history` | `ap_optical_treatment` | `ap_uuid`，无 UUID 时规范化 MAC；不使用 AP 名称 | AP 与 SWITCH 分侧；真实变化，单 AP/side 最多 10 条 |

约束已固化：首次观测只写 Current；相同状态只更新 `last_seen_at`；状态变化才写 History；光衰台账按 `site_id + ap_identity` 唯一更新，不按采集次数新增行。

## 业务规则

- 保留 AP/SWITCH 两侧光衰，展示和导出读取 bounded current/treatment authority。
- 无测量、无模块元数据且状态为 `no_module`/未知的记录不创建伪 Current；不会因为 AP 型号字符串生成 WA6522 光衰事实。
- `-13.90 dBm` 的原有业务门限保持不变，边界测试仍判定为 `normal`。
- 非法/模糊 AP Identity 不做模糊跨站匹配；维修删除只清理 Current/treatment，History 保留审计证据。
- Trackside Export 在 bounded authority 下读取已持久化 treatment，不重新构造无限历史或触发 Update All。

## 兼容与风险

- 旧 HistoryStore/旧表仅保留兼容读取；迁移后 active site 的旧目标 history 表为 0。
- `_ReadonlyDatabase.connect_readonly()` 补齐后，Electron AC GET-only 查询继续复用 bounded Repository，不产生写入。
- 未修改 AP Identity 规则、LLDP 采集命令、业务模型、生产数据或生产目录。

## 验证证据

- 9 个 DEV active site：schema `2026.08.26.lldp_optical_bounded_current_history`、`quick_check=ok`、authority 均为 `bounded_v1`。
- LLDP/Optical history 最大深度不超过 10；`ap_optical_treatment` 重复键分组为 0。
- Python 相关回归：400 passed；Renderer：1209 passed；Electron：282 passed；两端 typecheck/build、compileall 通过。
- 宁波12号线真实数据：FIT-AP 992、optical_current 1,892、LLDP history 8,377、optical history 18,907、treatment 101。

结论：**数据模型重构与 bounded authority 切换 PASS；真实 GUI 全流程与 Trackside 历史解码性能仍为 PARTIAL。**
