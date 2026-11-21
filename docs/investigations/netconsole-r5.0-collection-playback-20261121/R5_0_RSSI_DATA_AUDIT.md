# RSSI 数据链路审计

## 原始证据

hzdt-09 归档原始 Syslog 第 107 行：

```text
MESH_ACTIVELINK_SWITCH: Switch an active link from 28.XSL-S-05_900a-759f-585f(35) to 28.XSL-S-04_900a-759f-573f(43)
```

Parser/数据库的 `old_rssi=35`、`new_rssi=43` 与原文一致，说明该 H3C 消息保存的是 RSSI 绝对值量级。Renderer 原实现执行 `rssi + 100` 后截断到 80，正值 43 变成 80，导致全部顶格。

## 修复

- 原值 1..120：保留 `raw_rssi`，按已验证契约归一化为负 dBm，语义 `ABSOLUTE_MAGNITUDE`。
- 原值 -120..0：原样作为 dBm，语义 `NATIVE_DBM`。
- NULL/非法类型：保持无数据，不填默认值。
- 数值超界：保留原值，语义 `OUT_OF_RANGE`，不悄悄截断。

API 同时返回 `raw_rssi`、`rssi` 和 `rssi_semantics`。Peer 图使用真实负 dBm 轴，柱宽为切入/切出时差，Tooltip 同时显示原始值、归一化值和语义。

hzdt-09 15:47–15:50 只读验证：20 条切换，原始值范围 27..51，归一化范围 -51..-27 dBm，不再全部映射到统一最大值。
