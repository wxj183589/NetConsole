# ZTE 轨旁交换机 Adapter

> 2026-07-29 补充：设备详情 Profile v3 保持七条固定只读命令，普通刷新不再按端口追加光模块 detail；轨旁光衰更新使用每设备一次 SSH 会话、一次 `show version` 和一次 `show opticalinfo brief` 的快速路径。当前实机验证声明仅覆盖 C89E-4 Release，不外推到整个 ZXR10/5960X 系列。

## 当前范围

当前登记：

- vendor：`ZTE`
- platform：`ZXR10`
- product family：`C89E`（现场）/ `5960X-ES`（文档 fixture）
- reference version：`C89E-4 V1.9.0` / `5960X-ES V2.00.20.03`
- 生产详情 Command Profile：`zte.zxr10.switch.generic.device-inventory.v3`

2026-07-28 已按“一台、两台、其余设备”的顺序连接截图中的 11 台 C89E-4 V1.9.0，并发最高保持 2，均只执行 `show version`、`show interface brief`、`show opticalinfo brief`、`show lldp neighbor brief`、`show lldp entry`。五条命令全部成功：10 台车站交换机各解析 100 条接口和 100 条光模块，核心交换机解析 150/150 条，合计 1,150 条接口、1,150 条光模块和 167 条当前 LLDP 邻居。另有两台车站 C89E-4 完成设备详情 Profile v3 七条固定命令验证，`show running-config switchvlan` 是端口 mode/Native/成员/PVID 主来源，`show vlan` 仅以 PvidPorts 校验或回退 PVID。raw 仅保留在业务数据根；未执行完整配置、文件、Ping、诊断或任何写操作。因此 C89E-4 Release 状态为 `REAL_DEVICE_VERIFIED`，但不宣称 ZXR10 全系列兼容。

## 能力状态

| 能力 | 状态 | 第一阶段边界 |
| --- | --- | --- |
| SSH | `LOCALLY_OBSERVED` | C89E-4 V1.9.0 登录、提示符和只读命令已验证 |
| 设备版本 | `REAL_DEVICE_VERIFIED` | C89E-4 已验证；5960X-ES 仍为 `DOCUMENT_SAMPLE_ONLY` |
| 接口摘要 | `REAL_DEVICE_VERIFIED` | C89E 摘要已验证 |
| 接口详情 | `DOCUMENT_SAMPLE_ONLY` | 尚未执行 `show interface`；设备也尚未提供 `show interface description` |
| 光模块摘要 | `REAL_DEVICE_VERIFIED` | C89E 摘要及额外 `Mode` 列已验证 |
| 光模块详情 | `IMPLEMENTED_UNVERIFIED / REAL_DEVICE_PENDING` | 仅保留显式 opt-in 的受控诊断路径；普通详情和轨旁快速刷新都不逐端口执行 |
| LLDP | `REAL_DEVICE_VERIFIED` | C89E Brief/Entry 已进入默认采集；V2 仍待现场复核 |
| AP 自动匹配 | `IMPLEMENTED` | 复用现有 LLDP 与 AP Identity 匹配链；无唯一依据时保留未匹配，不猜测 |
| 双向光衰 | `SAMPLE_REQUIRED` | 仅有单端光功率时不计算双向光衰 |
| 运行配置解析 | `FIXTURE_ONLY` | 可从脱敏 fixture 动态提取接口 mode/VLAN；不硬编码局点 VLAN |
| 配置下发 | `UNSUPPORTED` | `write` 不进入只读 Profile，本次未执行 |

`enable 15` 仅作为可选 Profile 字段。仓库、测试、文档和日志不保存手册默认密码；需要特权且没有受控 secret 时失败关闭。

## 光模块状态合同

ZTE 光模块状态由同一个归一化器服务于 parser、Repository 读取、设备详情、轨旁业务、任务结果和导出：

- 设备返回 `offline` 或明确无模块时为 `no_module`，模块厂商、PN、Rev、SN、模式、RX/TX、温度、电压、电流和原生阈值全部清空；
- 原始状态为 `Unknown`，或接收光功率为 `N/A`/缺失时为 `no_light`，原因固定为“设备未返回接收光功率”；
- 只有 ZTE 原生 RX/TX 低高阈值参与异常判断；严格低于低阈值或严格高于高阈值才为 `abnormal`，等于低阈值仍为正常；
- 其余有效模块为 `normal`，不使用 H3C 的通用无光阈值。

brief 刷新可在模块仍存在时保留既有 detail 的稳定身份字段；一旦进入 `no_module` 就清空这些字段，后续重新插入模块也不会复用旧序列号。旧数据库记录在读出时同样经过归一化，不需要修改 SQLite schema 或批量重写历史数据。

## 采集路径与任务边界

- 普通 `device.inventory.collect` 固定执行 Profile v3 的七条只读命令：版本、接口摘要、交换 VLAN 配置、VLAN、光模块摘要和两条 LLDP。默认不追加 `show opticalinfo <interface>`。
- 轨旁光衰更新对每台 ZTE 设备只建立一个会话，只执行 `show version` 和一次 `show opticalinfo brief`；接口和 LLDP 关系读取数据库已有快照，不在逐行查询时连接设备。
- 同一局点、同一更新范围的活动任务复用已有 Task ID；设备列表先去重并受控并发，取消任务时关闭当前设备会话。
- 轨旁列表、统计、筛选项、导出和自动任务目标只包含 `work_scope_status=included` 的设备。Worker 在建立 SSH 前再次读取设备状态；若期间变为 `excluded`，记录“设备当前工作状态为暂不参与，已自动排除”并按跳过处理。建设分期不直接决定工作范围，改回 `included` 后自动重新进入候选；用户明确发起的手动只读设备操作不受此自动过滤限制。

## 采样 Artifact

`switch_vendor_sample_collect` 的下载名称为：

该任务第一阶段只接受 ZTE Adapter；H3C 保留既有采集链，不生成带 ZTE Parser 元数据的厂商采样 ZIP。

```text
zte-adapter-sample-<device>-<timestamp>.zip
```

ZIP 固定包含：

```text
manifest.json
command-status.json
version.txt
interface-brief.txt
interface-detail.txt
optical-brief.txt
optical-detail.txt
lldp-global.txt
lldp-interface.txt
session-metadata.json
```

任务逐命令记录成功、不支持、超时、分页数量和输出大小；单条候选不支持不会导致整个采样崩溃。Artifact 通过随机标识和清单绑定局点、owner、task 和受控输出根，不接受前端路径参数，并在写入前脱敏设备凭据。

## 后续清单

剩余事项：

1. 验证 `terminal length 0`、分页提示、空格续页和长输出终止行为。
2. 采集 `show interface` 与指定接口详情脱敏样本；在设备补充 `show interface description` 前，仅从受控运行配置快照解析描述。
3. 如后续需要逐端口诊断，在授权现场单独复核 opt-in detail 采集、单接口失败部分成功，以及 Vendor/阈值与页面显示；不得重新放入普通或轨旁快速刷新。
4. 在 5960X-ES V2 上复核已实现的 LLDP Brief/Entry Parser。
5. 验证 `show hardware`、`show serial-number`、`show system-info`，再决定是否扩展详情 Profile。
6. 单独设计 ZTE 配置中心、只读文件管理、CLI Ping 和诊断能力；不得因命令文本已提供就直接开放。
7. 继续复核 AP 匹配歧义、双端 ZTE 光衰和不同软件版本/型号兼容性。

后续仍只使用脱敏真实 Artifact 补充 fixture 和 Parser，不使用编造输出作为验证证据。
