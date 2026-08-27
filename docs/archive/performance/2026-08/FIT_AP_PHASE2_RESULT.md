# FIT-AP Phase2 结果

日期：2026-08-26

## 结论

FIT-AP 当前页批量加载已经存在并在真实 DEV 数据上生效。本轮没有重复实现，也没有修改 AP Identity、AC 资源模型或分页契约。

## DEV 实测

| 局点 | page 1 | page 2 | detail | 总 AP |
| --- | ---: | ---: | ---: | ---: |
| 杭州 10 号线 | 170ms | 164ms | 168ms | 491 |
| 宁波 10 号线 | 170ms | 169ms | 168ms | 591 |
| 宁波 12 号线 | 303ms | 316ms | 301ms | 992 |

各页面请求约 31–33 次 SQL，详情约 38–40 次 SQL；页面明细通过批量 `list_fit_ap_details_for_macs` 获取，没有按 AP 逐行发起 N+1 查询。宁波 10 号线个别真实数据缺少 radio detail，属于数据可用性 PARTIAL，不是性能回归。

## 验证

FIT-AP、Trackside 相关 Python 定向测试 109 passed；Ruff 与 compileall 通过。下一步保留真实数据缺口证据，不在验收阶段现场补数据或修改业务模型。
