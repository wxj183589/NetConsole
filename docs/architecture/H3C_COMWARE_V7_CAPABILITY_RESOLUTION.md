# H3C Comware V7 能力解析设计

## 目标

NetConsole 面向现场运维人员。只要不存在真实的配置、认证或跨厂商误操作风险，设备识别、能力选择和任务恢复应优先自动兼容；未登记 Patch/Release 不应成为低风险只读能力的硬门槛。

本设计只覆盖 H3C Comware V7 的能力解析和现有 AC/SFTP 接入，不创建第二套无线业务模型，也不改变 FIT-AP、Radio、Mesh-Link、MR 的领域数据结构。

## 解析层次

```text
vendor
  -> os family
    -> major version
      -> normalized role
        -> capability
          -> optional release override
```

当前实现集中在 `src/netconsole/services/device_command_profile_service.py`，设备角色归一化集中在 `src/netconsole/models/device_detail.py`：

- H3C + Comware + V7 进入 `h3c_comware_v7`；
- H3C 无线控制器能力进入 `h3c_comware_v7_wireless_controller`；
- `AC`、`wireless_ac`、`wlan_controller`、`controller` 和 `wireless_controller` 统一为 `wireless_controller`；
- `R1608P01`、`R2619P08`、`R9999P99` 等 Release 保存为诊断元数据，不是默认 allow-list；
- 已验证的 Release 差异可增加 selector 为 `R1608P01` 的 exact override。

Profile 选择优先级是：

1. Release exact override；
2. role + major family；
3. family common/read-only Profile；
4. 运行时安全只读探测或 fallback；
5. unsupported。

## AC 能力

`H3cAcCommandProfile` 保留 AC 业务层现有属性接口，但命令由 family capability resolver 提供。共同的 Comware 命令包括会话分页、版本、CPU/内存、设备信息和 HTTPS 查询；无线能力按 capability 分开声明：

- `wlan_ap_all`
- `wlan_ap_address`
- `wlan_ap_radio`
- `wlan_ap_radio_verbose`
- `wlan_ap_connection_record`
- `wlan_ap_radio_type`
- `wlan_ap_unauthenticated`
- `wlan_ap_lldp`
- `wlan_ap_verbose_all` / `wlan_ap_verbose_name`

低风险只读能力可以携带 fallback command；写配置命令不采用盲目 fallback。AC 采集只把 required command 失败视为资源快照失败；可选 WLAN 命令失败保留已采集资源，记录 `warnings` 和 `WLAN_OPTIONAL` skip。

## SFTP 安全边界

`device.sftp.enable` 仍是 `controlled_write`，但 H3C Comware V7 的 `V7` selector 表示 major family，而不是完整 Release 白名单。执行前必须确认：

- vendor 是 H3C；
- platform/os family 是 Comware；
- major 是 V7；
- role 是已知的 switch、wireless_controller 或 mobile_router；
- SSH 已认证、SFTP 子系统明确不可用且用户已授权。

Huawei、ZTE、未知厂商、未知平台、未知 major 和认证/网络失败都不能回退到 H3C 命令。

## 数据库与兼容性

本次没有数据库 schema、设备事实表或现有设备数据迁移。`software_release` 是解析层事实字段；历史 `device_facts` 没有该列时，完整 `software_version` 仍可解析 Release。已有 exact Profile 不删除，今后定位为 release override。

## 验证状态

自动化测试覆盖 V7 已知/未知 Release、role alias、override 优先级、SFTP family 安全边界和 optional WLAN warning。没有连接真实 AC；现场验证仍标记为 `REAL_DEVICE_PENDING`。
