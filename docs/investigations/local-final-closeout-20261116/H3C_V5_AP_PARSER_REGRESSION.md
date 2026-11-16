# H3C V5 FIT-AP 解析器回归报告

状态：`PASS`（本地材料与专项回归）；现场真实 AC 采集：`FIELD_VALIDATION_PENDING`。

## 根因与修复

H3C V5 `AC-fit-AP.txt` 在 AP 表头前输出两行状态图例：

```text
C = Config, R = Run, KU = KeyUpdate, KC = KeyCfm
M = Master, B = Backup
```

旧逻辑把以 `M` 开头的图例当成 AP 行，形成假 AP `M = Master,`。修复位于 `wlan_ap_parser.py`：仅跳过至少两个完整、已知 code/label 的状态图例，不用 `M` 前缀过滤 AP 名称；同时保留 `M` 真实 AP 名称、Master/Backup 状态和 V7/V9 状态兼容映射。

## 真实材料复核

材料：`D:\study\NetConsole-Workspace\diagnostic\ap-materials-audit-20261115\AC-fit-AP.txt`。

| 指标 | 修复前基线 | 修复后 |
| --- | ---: | ---: |
| AP 解析行 | 495 | 494 |
| 唯一 AP 名称 | 495 | 494 |
| `M = Master,` 假 AP | 1 | 0 |
| `C = Config,` 假 AP | 可能被旧宽规则影响 | 0 |
| 真实状态 | `R/M`、`I` | `R/M`、`I` |

合并台账指标保持不变：LLDP 464、精确确认 AP 422、`PENDING_DEVICE_TYPE` 42、`AC_ONLY_AP` 69、LLDP 冲突 0。AC-only 不伪造交换机、端口或站点归属。

## 回归

- 新增真实 M 前缀 AP 与精确 `M = Master, B = Backup` 图例测试。
- `tests/test_ac_management.py`：232 passed。
- `tests/test_ap_ledger_service.py`：专项通过并保持原始观察、待确认、AC-only、冲突边界。
- 合并定向测试：`tests/test_ac_management.py tests/test_ap_ledger_service.py tests/test_task_center.py tests/test_job_center_web_api.py`，354 passed。

未访问生产数据、真实 AC、真实交换机或现场设备。
