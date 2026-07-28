# ZTE 轨旁交换机 Adapter

> 2026-07-28 补充：设备详情 Profile v3 在两台车站 C89E-4 上完成七条只读命令验证。`show running-config switchvlan` 是端口 mode/Native/成员/PVID 主来源，`show vlan` 仅以 PvidPorts 校验或回退 PVID；每台各执行一次，中心设备不纳入轨旁 AP 业务结论。

## 当前范围

当前登记：

- vendor：`ZTE`
- platform：`ZXR10`
- product family：`C89E`（现场）/ `5960X-ES`（文档 fixture）
- reference version：`C89E-4 V1.9.0` / `5960X-ES V2.00.20.03`
- 生产详情 Command Profile：`zte.zxr10.switch.generic.device-inventory.v3`

2026-07-28 已按“一台、两台、其余设备”的顺序连接截图中的 11 台 C89E-4 V1.9.0，并发最高保持 2，均只执行 `show version`、`show interface brief`、`show opticalinfo brief`、`show lldp neighbor brief`、`show lldp entry`。五条命令全部成功：10 台车站交换机各解析 100 条接口和 100 条光模块，核心交换机解析 150/150 条，合计 1,150 条接口、1,150 条光模块和 167 条当前 LLDP 邻居。首台当前设备原文报告 35 个邻居，区别于脱敏回归样本的 36 条，Parser 对 Brief/Entry 均解析 35 条且无警告。raw 仅保留在业务数据根；未执行完整配置、文件、Ping、诊断或任何写操作。因此 C89E-4 状态为 `REAL_DEVICE_VERIFIED`，但不宣称 ZXR10 全系列兼容。

## 能力状态

| 能力 | 状态 | 第一阶段边界 |
| --- | --- | --- |
| SSH | `LOCALLY_OBSERVED` | C89E-4 V1.9.0 登录、提示符和只读命令已验证 |
| 设备版本 | `REAL_DEVICE_VERIFIED` | C89E-4 已验证；5960X-ES 仍为 `DOCUMENT_SAMPLE_ONLY` |
| 接口摘要 | `REAL_DEVICE_VERIFIED` | C89E 摘要已验证 |
| 接口详情 | `DOCUMENT_SAMPLE_ONLY` | 尚未执行 `show interface`；设备也尚未提供 `show interface description` |
| 光模块摘要 | `REAL_DEVICE_VERIFIED` | C89E 摘要及额外 `Mode` 列已验证 |
| 光模块详情 | `IMPLEMENTED_UNVERIFIED / REAL_DEVICE_PENDING` | 在线模块已接入 `show opticalinfo <safe-interface>`；以用户提供的 C89E 现场输出和 5960X 文档 fixture 回归，当前开发环境未重新连接设备 |
| LLDP | `REAL_DEVICE_VERIFIED` | C89E Brief/Entry 已进入默认采集；V2 仍待现场复核 |
| AP 自动匹配 | `SAMPLE_REQUIRED` | 不生成占位或虚假关系 |
| 双向光衰 | `SAMPLE_REQUIRED` | 固定 `NOT_VERIFIED / REAL_DEVICE_SAMPLE_REQUIRED` |
| 运行配置解析 | `FIXTURE_ONLY` | 可从脱敏 fixture 动态提取接口 mode/VLAN；不硬编码局点 VLAN |
| 配置下发 | `UNSUPPORTED` | `write` 不进入只读 Profile，本次未执行 |

`enable 15` 仅作为可选 Profile 字段。仓库、测试、文档和日志不保存手册默认密码；需要特权且没有受控 secret 时失败关闭。

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
3. 在授权现场复核在线模块 detail 采集、单接口失败部分成功，以及 Vendor/阈值与页面显示；当前仅有用户提供的脱敏现场样本和自动测试证据。
4. 在 5960X-ES V2 上复核已实现的 LLDP Brief/Entry Parser。
5. 验证 `show hardware`、`show serial-number`、`show system-info`，再决定是否扩展详情 Profile。
6. 单独设计 ZTE 配置中心、只读文件管理、CLI Ping 和诊断能力；不得因命令文本已提供就直接开放。
7. AP 实际匹配、歧义处理、双端光衰和不同软件版本/型号兼容验证。

后续仍只使用脱敏真实 Artifact 补充 fixture 和 Parser，不使用编造输出作为验证证据。
