# H3C Comware V9 Capability 真实设备验收

日期：2026-09-13

## 目标设备

- 站点：`hzl10 / 杭州地铁10号线`
- 设备：`251-无线控制器-主`
- 地址：`10.92.250.251`
- 型号：`WX3540X`
- 厂商/平台：`H3C / Comware`

## 版本事实

真实 SSH 只读探测 `display version` 成功，解析为：

- software version：`9.1.081`
- software release：`R1615P01`
- major：`V9`
- role：`wireless_controller`
- capability：`h3c_comware_v9_wireless_controller`

版本探测在 AC、FIT-AP 和设备详情命令计划之前执行；探测失败或 major 不确定时不默认 V7。

## 真实只读采集

- AC：17 个命令全部成功，AC 摘要更新成功。
- FIT-AP 资源：870 条更新成功。
- FIT-AP verbose：870 条详情更新成功，失败 0。
- BSSID：572 条解析成功。
- LLDP：572 条 AC 侧记录解析成功；设备详情 LLDP 邻居 12 条更新成功。
- 连接记录：587 条更新成功。
- 设备详情：12 个命令全部成功；接口 63、光模块 20、LLDP 邻居 12。

## API / GUI 边界

使用真实采集后的数据执行只读 API 查询：

- `/api/ac-management/summary`：HTTP 200，AP 总数 870。
- `/api/ac-management/aps`：HTTP 200，总数 870。
- `/api/device-management/devices/{device_uuid}`：HTTP 200，返回 fact、interfaces、optical_modules、lldp_neighbors 等详情结构。

GUI 前端构建和 Electron 宿主门禁均通过；本次未执行需要设备写权限的 GUI 动作。

## 自动化门禁

- 定向 H3C/AC/设备详情回归：PASS
- Python full：`4858 passed, 2 skipped`
- Renderer：`1300 passed`，typecheck/build PASS
- Electron：`298 passed`，typecheck/build PASS
- Architecture：`12/12 passed`

## 安全边界

- `PRODUCTION_MANUAL_MUTATION=NO`
- `DEVICE_CONFIG_MUTATION=NO`
- 未执行 SFTP enable、AP console enable、配置保存或手工 SQL。
- Production rollback/storage registry baseline failure 为 `OUT_OF_SCOPE`，本功能不修改、不吸收。

## 状态

`READY_FOR_RELEASE`
