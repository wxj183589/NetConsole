# Real FIT-AP Test

日期：2026-08-26

数据根：`D:\NetConsoleData-dev`；页面大小 50；验收起点 HEAD：`e8b826b9b6d3e799fc2bd71afe07ece07b4b2769`。

## 本轮 bounded current 实测

宁波地铁12号线真实只读查询：FIT-AP resources 992 条；第一次批量资源读取 92.31ms / 12 SQL，第二次 91.59ms / 12 SQL；当前光衰 946 条、当前 treatment 101 条。页面第 1 页 50 条、总数 992，319.60ms / 32 SQL；首个 AP 详情 324.55ms / 39 SQL，详情可用。未发现逐 AP 的列表 N+1 查询。

阈值与空模块边界：`-13.90 dBm` 仍判定为 `normal`；仅有 `no_module`、无测量/模块元数据的 WA6522 样例不写入 `optical_current`。

## 真实局点结果

| 局点 | AP 总数 | page 1 | page 2 | 详情打开 | SQL/page |
| --- | ---: | ---: | ---: | ---: | ---: |
| 杭州 10 号线 | 491 | 170ms | 164ms | 168ms，radio detail 可用 | 33 / 33 |
| 宁波 12 号线 | 992 | 303ms | 316ms | 301ms，radio detail 可用 | 31 / 31 |
| 宁波 10 号线（补充） | 591 | 170ms | 169ms | 168ms，部分 radio detail 缺失 | 33 / 33 |

详情请求约 38–40 次 SQL，页面明细通过批量 `list_fit_ap_details_for_macs` 读取，没有发现按 AP 逐行查询的 N+1 模式。分页时间稳定，没有发现异常查询或页面随 AP 数量线性放大的迹象。

## 结论

**PASS（性能与批量加载）**。本轮只读查询和自动化测试验证 bounded current/treatment 路径；宁波 10 号线个别详情缺少真实 radio detail，标记为数据完整性 PARTIAL；没有修改数据或在验收现场补写资源。
