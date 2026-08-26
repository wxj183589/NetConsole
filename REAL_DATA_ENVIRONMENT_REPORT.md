# Real Data Environment Report

日期：2026-08-26

## 环境

- 验收起点 HEAD：`e8b826b9b6d3e799fc2bd71afe07ece07b4b2769`。
- 本轮工作区包含 LLDP/光衰 bounded current/history 变更；生产根 `D:\NetConsoleData` 未读取、未写入、未复制、未迁移。
- `data_root`：`D:\NetConsoleData-dev`。
- active site：9 个；当前活动局点：宁波地铁12号线。
- `devices.db` 合计：722,067,456 bytes（约 688.6 MiB）。

## 数据库与规模

| 局点 | devices.db | devices | FIT-AP resource | optical_current | LLDP current | LLDP history | optical history | treatment |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 宁波地铁12号线 | 165,232,640 | 100 | 992 | 1,892 | 992 | 8,377 | 18,907 | 101 |
| 杭州地铁10号线 | 355,860,480 | 34 | 491 | 984 | 492 | 3,806 | 8,646 | 85 |
| 宁波地铁10号线 | 117,211,136 | 116 | 591 | 1,184 | 592 | 5,912 | 11,508 | 49 |
| 宁波地铁1号线 | 50,585,600 | 122 | 685 | 1,370 | 685 | 6,038 | 8,488 | 74 |
| 宁波地铁6号线 | 27,254,784 | 164 | 602 | 1,204 | 602 | 3,008 | 3,314 | 13 |

其余 4 个 active site 为零或 demo 级别数据，均完成 schema/完整性检查。`tasks.db` 与其它 MESH SQLite 仅作只读统计和查询，不执行迁移。

## 数据模型验收

- schema：`2026.08.26.lldp_optical_bounded_current_history`。
- LLDP authority：`bounded_v1`；optical authority：`bounded_v1`。
- 9 个 active site 的 `quick_check` 均为 `ok`。
- 旧 LLDP/optical history 目标表、迁移 outbox/state 均为 0。
- LLDP 与 optical 最大历史深度均不超过 10；空数据局点为 0。
- `ap_optical_treatment` 重复键分组为 0。

结论：**PASS**。数据完整性检查只使用 `D:\NetConsoleData-dev`；未执行生产迁移、删除或 VACUUM。
