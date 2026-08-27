# Trackside Performance After LLDP Refactor

日期：2026-08-26

| 操作 | 旧证据 | 当前 DEV 实测 | 结果 |
| --- | ---: | ---: | --- |
| Trackside snapshot first read | 72.4s（旧导出 snapshot） | 936.59ms，1,247 行 | PASS（页面 snapshot） |
| Trackside snapshot cache hit | 未固化 | 3.53ms | PASS |
| Trackside XLSX direct export | 约 77.4s | 28,140.38ms；snapshot 25,289ms | PARTIAL |
| 8-way read/export/query | 未验收 | 8/8 完成，锁错误 0 | PASS |

LLDP current/history 收口后，Trackside 读取不再依赖无限 LLDP 历史；但导出 enrichment/HistoryStore 解码仍占主要时间。该剩余热点不得在本验收报告中隐含为已解决。
