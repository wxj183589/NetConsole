# Engineering Current/Recent10 Migration Report

日期：2026-08-26
数据根：`D:\NetConsoleData-dev`
main commit：`afa35c06`
生产保护：`PRODUCTION_DATA_TOUCHED=NO`

## 执行

1. 只读 inventory。
2. 对每个 DEV `devices.db` 使用 SQLite Backup API 建候选库。
3. 先重放旧 direct history，再重放 source Current；Current 胜过旧历史，避免旧时间戳覆盖当前事实。
4. 删除候选中的 Legacy HistoryStore shard/outbox/state 和旧 AP Radio/LLDP/Optical 直接历史目标。
5. 对 Current/Recent、authority marker、quick_check、重复键和最大深度做候选门禁。
6. 仅在候选全部通过后执行 DEV cutover；回滚副本校验后清理，未触碰生产根。

## 迁移汇总

| 类别 | source rows | true changes | After Recent rows | max/resource |
| --- | ---: | ---: | ---: | ---: |
| Radio | 124,977 | 16,881 | 13,560 | 10 |
| Interface | 208,261 | 93,769 | 37,355 | 10 |
| Device LLDP | 46,568 | 6,416 | 4,159 | 10 |
| Device Optical | 156,845 | 70,974 | 24,628 | 10 |
| AP LLDP | bounded source | — | 27,145 | 10 |
| AP Optical | bounded source | — | 50,863 | 10 |

After Current 汇总：Radio 6,729、Interface 13,381、Device LLDP 4,093、Device Optical 7,542、AP LLDP 3,365、AP Optical 6,638；Treatment 322，重复键 0。

## 门禁

- 9/9 迁移目标 `PRAGMA quick_check=ok`。
- 9/9 `engineering_history_authority=retired`。
- 9/9 history directory absent；outbox/state rows 0。
- Current state parity：PASS；candidate source Current 覆盖旧 history 回放结果。
- idempotence/retention：PASS；同状态不增长，Recent 最大 10。
- 迁移输出：`D:\study\diagnostic\NetConsole\engineering_recent10_cutover.json`。
