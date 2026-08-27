# Trackside Performance After Current Model

日期：2026-08-26

## 真实 DEV 数据

- 根：`D:\NetConsoleData-dev`；局点：宁波地铁12号线。
- 业务行：1,247；身份 distinct：948；unresolved：302；ambiguous：0；partial：false。
- 当前 optical/treatment 读取：`optical_current` 1,892 行，`ap_optical_treatment` 101 行。

## 实测

| 操作 | 优化前证据 | 当前实测 | 结果 |
| --- | ---: | ---: | --- |
| snapshot miss / first read | 72.4s（旧导出路径） | 936.59ms，1,247 行 | PASS（页面快照） |
| snapshot hit / second read | 未单独固化 | 3.53ms，revision 不变 | PASS |
| direct XLSX prepare/render | 约 77.4s | 28,140.38ms；snapshot 25,289ms；render 1,895ms | PARTIAL |
| 8-way page/export/FIT query | 未验收 | 8/8 PASS；锁错误 0 | PASS |

## 判断

Current/treatment authority 已避免导出期间重建无限 optical history；页面 cache hit 明显降低。导出仍有约 25.29s 的 snapshot/enrichment 成本，且历史正式 Export Process 仍观测到约 74.8s，因此不能宣称 Trackside snapshot build 已完全解决。

下一步应单独处理 Trackside HistoryStore 历史分片/压缩解码与批量边界；本报告不建议在验收阶段现场打补丁。
