# Command Semantic Matrix

本矩阵是 Phase 1.5 的只读语义审计。它记录现有入口、命令来源、解析器和 DTO 的边界，不创建新 command operation，不修改 `resources/device_command_profiles.json`、`TracksideCommandProfile` 或 `FIT_AP_OPTICAL_COMMANDS`。

## 现有采集矩阵

| 领域 | 入口 | 角色 | 命令来源 | Parser | DTO | 是否适合统一 |
| --- | --- | --- | --- | --- | --- | --- |
| 设备详情 / 通用设备库存 | `device_detail_collect` → `run_device_inventory_refresh` → `collect_h3c_device_details` | H3C switch、H3C `wireless_controller`、ZTE switch、H3C `mobile_router` | `resources/device_command_profiles.json` 经 `device_command_profile_service` 解析；现有 operation 为 `device.inventory.collect` | H3C：`H3CParser` 及 `adapters/h3c/h3c_lldp_parser.py`、`h3c_optical_parser.py`；ZTE：`parsers/zte/zxr10.py`、`parsers/zte/vlan.py` | `DeviceFactDTO`、`DeviceLldpNeighborDTO`、`DeviceDetailDTO`；接口/光模块/LLDP 事实写入 `DeviceFactRepository` | 只适合统一稳定字段/规范化和 Profile 校验契约；不与轨旁 AP 或 FIT-AP 采集器统一 |
| 轨旁交换机 / 轨旁 AP 光衰关联 | `trackside_ap_optical_update` → `run_trackside_ap_optical_update` → `collect_trackside_optical` → `TracksideSwitchAdapter` | 车站交换机：H3C Comware、ZTE ZXR10 5960X-ES | 独立 `TracksideCommandProfile`；H3C/ZTE 各自的轨旁 profile 和 `TRACKSIDE_OPTICAL_COMMANDS`，不是设备库存 Profile | H3C：`parsers.h3c.interface_parser`、`lldp_parser`、`transceiver_parser`；ZTE：`parsers.zte.zxr10`/`vlan` 的接口、LLDP、光模块解析与合并 | 内部 `TracksideDeviceCollectionResult`；业务查询/适配器目录使用 `TracksideApBusinessRowDTO`、`TracksideSwitchAdapterDTO` | 不统一入口、命令集、站点范围、AP 关联和持久化语义；可复用底层字段规范化和部分厂商 parser |
| AC / FIT-AP 光衰 | `AcOpticalService.refresh_fit_ap_optical` → `collect_h3c_fit_ap_optical` | AC / `wireless_controller` 管理的 FIT-AP；结果是 AP 侧光衰与其交换机链路事实 | `FIT_AP_OPTICAL_COMMANDS`：AC/控制台采集链中的固定只读命令，经 `command_guard` 校验 | `parse_fit_ap_optical` → `parse_fit_ap_lldp`、`parse_fit_ap_transceiver`；组合 `fit_ap_lldp_neighbor_parser` 和 H3C transceiver parser | 内部 `FitApOpticalCollectResult`；查询边界为 `AcOpticalDTO`、`AcLldpDTO`/`AcCurrentLldpDTO` | 不统一为设备/轨旁命令入口；可共享光功率、接口、LLDP 关系的规范化字段，但 AP 身份、AC 作用域、状态生命周期和持久化 DTO 保持独立 |

命令来源与领域的关键关系是：设备库存 Profile 描述“被管理设备的详情事实”，轨旁 Profile 描述“车站交换机到轨旁 AP 拓扑/光衰关联”，FIT-AP 命令描述“AC 控制下的 AP 侧采集”。命令文本相似不代表 operation、目标身份或事实 owner 相同。

## 语义问题结论

### 设备 LLDP 与轨旁 LLDP 是否同一领域

不是同一领域。二者都使用 LLDP 协议，也可以共享接口名、邻居 MAC、邻居端口等底层规范化字段，但消费目的不同：

- 设备详情 LLDP 是某个受管设备的 inventory fact，随 `device.inventory.collect` 写入 `DeviceFactRepository`，对外投影为 `DeviceLldpNeighborDTO`。
- 轨旁 LLDP 是车站交换机侧的 AP 连接证据，需要站点/车站范围、轨旁 AP 身份、当前/历史关系和光衰关联，属于 `trackside.*` 领域。

因此不能因为 parser 或命令名称相近，就把轨旁 LLDP 塞进通用设备详情的任务或 DTO。

### 交换机光模块与 FIT-AP 光衰是否同一领域

也不是同一采集领域。交换机侧关注端口 DOM、模块状态和交换机端口；FIT-AP 侧关注 AP 资源、AC 作用域、AP 到交换机的 LLDP 关系以及 AP/交换机双侧状态。两者可以共享数值字段（例如接口、收发光功率、温度、阈值）的规范化，但不能直接合并命令入口、身份解析、成功/空数据/失败状态或事件持久化。

### 什么可以进入 `device.lldp.collect`

当前没有注册 `device.lldp.collect` operation。现有 `device.inventory.collect` 已把 LLDP list/verbose 作为设备详情 Profile 的步骤之一，覆盖当前四类设备角色。因此 Phase 1.5 不新增一个同名 operation，也不把现有轨旁或 FIT-AP 逻辑迁入。

如果未来确有独立 LLDP operation，其边界只能是：受管设备身份已确定、由设备 command profile 提供命令、结果写入通用设备事实并投影为设备 LLDP DTO；它不能接管站点交换机到 AP 的拓扑关联，也不能接管 AC/FIT-AP 的控制台采集。

### 仍应保留在哪些命名空间

| 命名空间 | 保留内容 |
| --- | --- |
| `device.inventory.collect` | 受管设备的版本、接口、交换机光模块和设备 LLDP inventory；角色差异由设备 Profile 选择 |
| `trackside.*` | 车站交换机采集、轨旁 LLDP、AP/交换机身份关联、轨旁光衰和站点范围 |
| `wireless_controller.*` / AC 领域 | AC 资源、FIT-AP 详情、AP 侧光衰、AC 作用域 LLDP 与 FIT-AP 生命周期 |

## DTO 与 parser 收敛边界

目前可视为稳定对外投影的 DTO 是 `DeviceFactDTO`/`DeviceLldpNeighborDTO`、`AcOpticalDTO`/`AcLldpDTO` 以及轨旁业务/适配器 DTO；若干采集器内部仍使用 `dict[str, object | None]` 和内部 Result dataclass，不应在本阶段把内部字典强行改成跨领域 DTO。

低层 H3C/ZTE parser 已存在复用关系：设备详情经 H3C adapter wrapper 使用通用 parser，轨旁适配器直接使用通用接口/LLDP/transceiver 或 ZTE parser，FIT-AP parser 组合 H3C LLDP 与 transceiver parser。这里的差异主要是领域适配、字段补全、身份匹配和持久化，而不是本阶段应通过复制或合并 parser 解决的重复实现。

本矩阵没有预先判定“全部统一”或“全部隔离”：稳定的接口名、MAC、光功率、LLDP 邻居基础字段可以在未来形成共享规范；命令 Profile、目标角色、站点/AC 作用域、身份匹配、状态生命周期和领域 DTO 需要继续各自负责。
