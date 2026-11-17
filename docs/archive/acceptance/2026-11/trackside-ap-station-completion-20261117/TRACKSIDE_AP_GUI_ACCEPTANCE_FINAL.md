# 杭州地铁9号线昌达路及491条轨旁 AP 验收

- 最终状态：`LOCAL_PASS_GUI_VERIFIED`
- 产品：NetConsole 旧版 v1.5.15
- HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- Branch：`codex-A/trackside-ap-template-station-closure-20261116`
- Site：`hzdt-09` / 杭州地铁9号线
- 实际数据根：`D:\NetConsoleData-dev`
- 本轮未修改源码、未 Push、未创建 PR、未升级版本、未打包。

## 昌达路结果

数据库只读核对发现正式 `昌达路` 已存在，本轮按唯一性规则未重复创建。实际 `station_id` 为 `station:0f0599c1f124`，Site 为 `hzdt-09`，原始站序为 `921`，对应业务站序 `31`，启用。12 条昌达路 AP 均使用该 ID。

## 21 个正式站点

| 站序 | 站名 | 实际 station_id | Site | 状态 | 原始 sort_order |
|---:|---|---|---|---|---:|
| 11 | 观音塘 | `station:5d9bedb16dac` | `hzdt-09` | 启用 | 901 |
| 12 | 新业路 | `station:40c3b77ed754` | `hzdt-09` | 启用 | 902 |
| 13 | 钱江路 | `station:a4395faf648f` | `hzdt-09` | 启用 | 903 |
| 14 | 江河汇 | `station:38f97ace5597` | `hzdt-09` | 启用 | 904 |
| 15 | 三堡 | `station:4d18471a239d` | `hzdt-09` | 启用 | 905 |
| 16 | 御道 | `station:7fa96f73fbb0` | `hzdt-09` | 启用 | 906 |
| 17 | 五堡 | `station:ee42d20bd8a6` | `hzdt-09` | 启用 | 907 |
| 18 | 六堡 | `station:fa6fb3f0c423` | `hzdt-09` | 启用 | 908 |
| 19 | 红普南路 | `station:101184a8d75d` | `hzdt-09` | 启用 | 909 |
| 20 | 九睦路 | `station:faadb3db157c` | `hzdt-09` | 启用 | 910 |
| 21 | 客运中心 | `station:94c1ddf54c41` | `hzdt-09` | 启用 | 911 |
| 22 | 乔司南 | `station:a72f109d3ff0` | `hzdt-09` | 启用 | 912 |
| 23 | 乔司 | `station:2bb2c381a95c` | `hzdt-09` | 启用 | 913 |
| 24 | 翁梅 | `station:96d66b54464a` | `hzdt-09` | 启用 | 914 |
| 25 | 临平南高铁站 | `station:dfc0b2d9920e` | `hzdt-09` | 启用 | 915 |
| 26 | 南苑 | `station:53fa57a1fb11` | `hzdt-09` | 启用 | 916 |
| 27 | 临平 | `station:1e45fc05f85e` | `hzdt-09` | 启用 | 917 |
| 28 | 邱山大街 | `station:28f664ece45a` | `hzdt-09` | 启用 | 918 |
| 29 | 荷禹路 | `station:1a9d419593fb` | `hzdt-09` | 启用 | 919 |
| 30 | 五洲路 | `station:ee2c319673c5` | `hzdt-09` | 启用 | 920 |
| 31 | 昌达路 | `station:0f0599c1f124` | `hzdt-09` | 启用 | 921 |

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



Site API 同时返回 33 个站点对象（31 个普通节点、2 个特殊节点）；其中包含历史/未来的额外节点及通用车辆段/停车场节点。本表要求的21个正式站点均唯一、启用、属于 `hzdt-09`。车辆段和停车场 AP 未伪造正线 station_id。
