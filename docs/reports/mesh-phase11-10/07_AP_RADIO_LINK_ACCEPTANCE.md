# AP、Radio、链路明细验收

## AP 情况

04 中 AP 统计按 AP 名称、MAC、站点、区间、链路角色、Radio、平均 RSSI、
最低 RSSI、最近 RSSI、信号质量和低信号比例展示。角色和 Radio 控件可重新
查询；数据不足时明确显示暂无数据。

## Radio

15 先切到 Radio 2，当前真实源没有 Radio 2 有效链路，页面显示空数据，
没有把 Radio 1 结果复制到 Radio 2；切回 Radio 1 后表格、图表和详情恢复。
HTTP/SQL trace 记录 Radio 2 raw query total=0。

## 链路明细

初始表格总数 108700，分页 100/page。真实操作结果：

| 操作 | 结果 |
| --- | --- |
| 角色选择“主链路”并点击筛选 | 总数 44470；当前 100 行全部 ACTIVE |
| 文本查询 Z04-27 | 总数 97；97 行实际值均包含 Z04-27 |
| 列设置启用“本端 CPU 利用率” | 应用后表头出现该列，并保存在本地表格配置 |
| 分页控件 | 显示 1…1087；数据页真实来自 links API |
| 空数据路径 | Radio 2 清晰提示，没有永久 loading |

02 是完整链路表截图；交互过程另见 ELECTRON_INTERACTION_TRACE.json。

结论：AP / Radio / Link Continuity / 链路明细 / 分页 / 列设置 PASS。
