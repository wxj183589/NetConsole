# Real FIT-AP Test

日期：2026-08-26

数据根：`D:\NetConsoleData-dev`；页面大小 50；最终代码：`02fde6e9c9487b7d8edee2a0ff556f56c0f3d847`。

## 真实局点结果

| 局点 | AP 总数 | page 1 | page 2 | 详情打开 | SQL/page |
| --- | ---: | ---: | ---: | ---: | ---: |
| 杭州 10 号线 | 491 | 170ms | 164ms | 168ms，radio detail 可用 | 33 / 33 |
| 宁波 12 号线 | 992 | 303ms | 316ms | 301ms，radio detail 可用 | 31 / 31 |
| 宁波 10 号线（补充） | 591 | 170ms | 169ms | 168ms，部分 radio detail 缺失 | 33 / 33 |

详情请求约 38–40 次 SQL，页面明细通过批量 `list_fit_ap_details_for_macs` 读取，没有发现按 AP 逐行查询的 N+1 模式。分页时间稳定，没有发现异常查询或页面随 AP 数量线性放大的迹象。

## 结论

**PASS（性能与批量加载）**。宁波 10 号线个别详情缺少真实 radio detail，标记为数据完整性 PARTIAL；没有修改数据或在验收现场补写资源。
