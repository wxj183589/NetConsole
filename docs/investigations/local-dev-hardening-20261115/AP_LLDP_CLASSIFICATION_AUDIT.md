# AP LLDP 分类审计

状态：`LOCAL_PARTIAL`（本地资料与分类逻辑已完成；现场设备验证仍为 `FIELD_VALIDATION_PENDING`）

## 范围与证据

- 分支：`codex-A/local-dev-hardening-20261115`
- 基线：`392e3274`
- 原始资料：`C:\Users\18358\Desktop\1q(1).zip`
- 解析源：`AC-fit-AP.txt`、`address.txt`、21 个车站文件。
- 原始文件未修改；解析结果写入 Workspace diagnostic，不写入生产或真实开发数据。

## 重新计算结果

| 指标 | 数量 |
| --- | ---: |
| 车站 | 21 |
| 原始 LLDP 邻居 | 464 |
| LLDP 驱动的确认 AP | 422 |
| `PENDING_DEVICE_TYPE` | 42 |
| `CONFIRMED_NON_AP` | 0 |
| `AC_ONLY_AP` | 69 |
| LLDP 冲突记录 | 0 |
| AC AP 解析行 | 495 |
| AC 地址记录 | 494 |
| AC 未匹配行 | 73 |
| 缺少交换机名称提示 | 26 |

42 条未被 AC 精确确认的 LLDP 邻居全部保留为待确认观察证据，没有静默丢弃，也没有全部降级为非 AP。分类依据优先级为：可靠设备类型证据、AC 完整 MAC 精确匹配、可验证 AP 资产证据；MAC OUI、名称前缀、IP 推端口和 MAC 尾号均不作为确认依据。

## 495 与 494 的差异

`AC-fit-AP.txt` 第 52 行是图例文本 `M = Master, B = Backup`，AP 解析器将其解析为一个非资产的 AP 名称 `M = Master,`；该行不在 `address.txt` 中。差异是输入格式中的图例行，不是代码硬编码或真实 AP 丢失。原始资料保留不变，审计工作簿中可追溯其来源。

## 实现结果

`ap_ledger_service.py` 现在先保留每条 LLDP 原始观察，再进行分类；AC 只提供确认和补充。输出包含标准导入表和审计工作表：`lldp_observations`、`pending_device_type`、`confirmed_non_ap`、`ac_only`、`conflicts`、`stats`。同一 MAC、同一非泛化名称、同一交换机本地端口出现不可解释复用时进入 `CONFLICT`，不覆盖旧证据。

验证：`tests/test_ap_ledger_service.py` 通过，且专项地面回归 212 passed、1 skipped。
