# AC 全快照 Delta 与 Syslog 对照

## 快照与 Delta

| 指标 | 数量 |
|---|---:|
| AC 快照 | 389 |
| AC 行 | 37,511 |
| 有 AP 位置的行 | 32,402 |
| 最新 MR 数 | 113 |
| 接受快照 | 387 |
| stale/incomplete 拒绝安全应用 | 2 |
| 旧时间快照 | 0 |

| Delta 类型 | 数量 |
|---|---:|
| ADDED | 213 |
| UPDATED | 9,057 |
| REMOVED | 174 |
| UNCHANGED | 28,089 |
| UNKNOWN | 152 |

AC `peer_ap_mac` 只作为精确物理 AP 身份种子，未使用模糊名称、反推 MAC 或跨站点匹配。stale/incomplete 记录保留在历史中，不生成删除型覆盖动作。

## Syslog 优先级边界

Syslog 与 AC 的比较使用 `CONSISTENT`、`SYSLOG_NEWER`、`AC_NEWER`、`STALE`、`UNKNOWN` 等现有状态；本次归档中以 120 秒新鲜度阈值统计为 `AC_NEWER=29`、`STALE=6`。回放只生成对照，不改变 Syslog Current，因此满足 AC 延迟快照不得无条件覆盖更新位置的边界。
