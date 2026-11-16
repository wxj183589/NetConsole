# AP 台账冲突与待确认报告

## 真实资料结果

本次 `1q(1).zip` 解析中自动冲突数为 0。42 条非 AP LLDP 邻居已按完整 MAC 不在 AC 地址表中的规则排除，不进入正式 AP 台账。26 条 AP LLDP 回显缺少交换机提示符，作为 `pending_switch` 证据保留，不猜测交换机身份。

## 冲突判定

适配器会保留原始来源并生成 `CONFLICT` 记录，不执行无条件覆盖：

| 场景 | 处理 |
| --- | --- |
| 同一 MAC 出现在不同站点/交换机/Local Interface | 保留各观察证据，移出自动匹配结果 |
| 同一站点、交换机、Local Interface 对应多个 MAC | 保留端口冲突，移出自动匹配结果 |
| AC MAC 与 LLDP MAC 不一致 | 标记冲突，不以名称覆盖 MAC |
| 同名但 MAC 不同 | 仅在没有 AC MAC 时允许精确名称兼容匹配；有 MAC 时不模糊匹配 |
| AC-only | `UNMATCHED`，不生成虚假交换机/端口 |

## 回归证据

`tests/test_ap_ledger_service.py` 覆盖：

- 多站点多源 LLDP 合并；
- 非 AP 邻居排除；
- Local Interface 与邻居侧 Port ID 区分；
- 来源元数据进入导入 payload；
- 同 MAC 跨站点/端口冲突；
- 同交换机端口多 MAC 冲突；
- 导入预览可读取 422 条正式行。

实际冲突为 0 不代表现场无冲突；它只表示当前提供的原始资料没有触发上述规则。现场新增资料需重新运行适配器并复核 `CONFLICT`、`UNMATCHED` 和 `pending_switch`。
