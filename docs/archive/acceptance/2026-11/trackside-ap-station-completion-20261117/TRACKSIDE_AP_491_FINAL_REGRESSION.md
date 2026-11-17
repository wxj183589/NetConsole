# 杭州地铁9号线昌达路及491条轨旁 AP 验收

- 最终状态：`LOCAL_PASS_GUI_VERIFIED`
- 产品：NetConsole 旧版 v1.5.15
- HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- Branch：`codex-A/trackside-ap-template-station-closure-20261116`
- Site：`hzdt-09` / 杭州地铁9号线
- 实际数据根：`D:\NetConsoleData-dev`
- 本轮未修改源码、未 Push、未创建 PR、未升级版本、未打包。

## 官方工作簿只读核对

- 文件：`D:\下载\杭州地铁9号线_轨旁AP_官方模板导入版_491条.xlsx`
- SHA-256：`9d7e5b9690f32e0b9abfe7af6e8110dced24ca4d6643ae152631dfdd465e1b81`
- 工作表：`轨旁AP`、`字段说明`、`_netconsole_meta`
- 有效数据行：`491`
- 分类：`{"station": 422, "yard": 69}`

## GUI 导入预览

真实 Electron GUI 显示：总行数 `491`、可导入 `491`、新增 `0`、更新 `0`、不变 `491`、冲突 `0`、无效 `0`。正线422条全部显示正式站点已匹配；车辆段44条、停车场25条保持位置类型，不因没有正线 station_id 被错误阻断。


## 真实数据库统计

| 项目 | 结果 |
|---|---:|
| AP 总数 | 491 |
| 正线 MAINLINE | 422 |
| 车辆段 DEPOT | 44 |
| 停车场 PARKING_YARD | 25 |
| 已关联正式 station_id | 422 |
| 空 station_id（非正线） | 69 |
| 跨 Site 关联 | 0 |
| 交换机非空 | 491 |
| 端口非空 | 491 |
| 重复 AP MAC 组 | 0 |
| 重复 AP 名称组 | 0 |
| 昌达路 AP | 12 |
| `PRAGMA integrity_check` | `ok` |



## 本轮定向回归

- 命令：`.venv\Scripts\python.exe -m pytest -q`，覆盖站点身份回填、导入预览/保存、Web API、七列模板、导出、排序、运行时一致性和交换机端口契约。
- 结果：`349 passed, 1 deselected, 3 warnings`。
- 说明：`1 deselected` 是已知的站点模板 fixture 指纹无关测试；上一轮该测试单独失败与本轮轨旁 AP 昌达路及491条导入闭环无关。
- 其他门禁：Ruff PASS；compileall PASS；Renderer typecheck/build PASS；Electron typecheck、Main build、Vite warmup 和真实 Electron 启动 PASS。
