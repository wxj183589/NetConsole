# Real FIT-AP Test

日期：2026-08-26
数据根：`D:\NetConsoleData-dev`
代码基线：`538db1c3`
生产保护：`PRODUCTION_DATA_TOUCHED=NO`

## 真实局点结果

| 局点 | AP 总数 | page 1 | page 2 | 详情打开 | 当前 radio |
| --- | ---: | ---: | ---: | ---: | ---: |
| 杭州地铁10号线 | 491 | 170ms | 164ms | 168ms，radio detail 可用 | 982 |
| 宁波地铁12号线 | 992 | 303ms | 316ms | 301ms，radio detail 可用 | 1,984 |

宁波12号线批量资源读取约 92ms / 12 SQL；页面约 32 SQL；详情约 39 SQL。页面明细使用批量 `list_fit_ap_details_for_macs`，未发现按 AP 逐行查询的 N+1。当前光衰与 treatment 读取使用 bounded Current/Treatment。

## 限制

- 本轮为只读 DEV 验收；没有 Update All、设备采集或真实数据补写。
- GUI 点击、完整翻页/返回矩阵需在最终提交后复验；宁波10号线的部分 radio detail 缺失属于数据完整性 PARTIAL，不现场修复。

结论：**服务端批量路径 PASS；完整 GUI 验收 PARTIAL。**
