# 事件查询审计

## MESH

查询只接受 `event_type='MESH_ACTIVELINK_SWITCH'`。普通 LinkUp/LinkDown 不进入事件列表或 Peer 区间。

窗口内查询额外读取一条窗口开始之前的有效切换。只有当前切换的新 BSSID 与下一条切换的旧 BSSID 精确一致时，二者之间才形成区间。区间可裁剪到窗口起点；最后一条证据不会无条件延长到窗口终点。事件稳定按真实事件时间与 id 排序，上限 500+截断标记。

## 丢包

丢包 SQL 使用相交条件：`started_at <= window_end` 且 `ended_at` 为空或 `ended_at >= window_start`。因此覆盖开始在窗外、恢复在窗内，或开始在窗内、恢复在窗外/未恢复的事件。结果按开始时间、id 倒序，默认 3 条，支持 limit/offset 和 total。

时间轴连续拖动会取消前一请求并防抖；页面卸载取消所有未完成请求。
