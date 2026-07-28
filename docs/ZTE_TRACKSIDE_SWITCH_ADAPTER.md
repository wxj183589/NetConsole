# ZTE 轨旁交换机 Adapter

## 第一阶段范围

当前只登记：

- vendor：`ZTE`
- platform：`ZXR10`
- product family：`5960X-ES`
- reference version：`V2.00.20.03`
- Command Profile：`zte_zxr10_5960x_es_v2`

本阶段没有连接真实 ZTE 节点。代码已具备设备模型、Adapter 注册、只读会话与分页框架、命令计划、厂商无关 DTO、文档样例 Parser、独立采样 Job、ZIP Artifact、API 和轨旁 AP 页面入口，但不宣称实机兼容。

## 能力状态

| 能力 | 状态 | 第一阶段边界 |
| --- | --- | --- |
| SSH | `SAMPLE_REQUIRED` | 登录、提示符和权限边界待真实节点验证 |
| 设备版本 | `IMPLEMENTED` | 基于手册样例，`DOCUMENT_SAMPLE_ONLY` |
| 接口摘要/详情 | `IMPLEMENTED` | 基于手册样例，待实机校准 |
| 光模块摘要/详情 | `IMPLEMENTED` | 基于手册样例，不保存为现场业务数据 |
| LLDP | `SAMPLE_REQUIRED` | 只登记七条候选命令，不进入默认采集 |
| AP 自动匹配 | `SAMPLE_REQUIRED` | 不生成占位或虚假关系 |
| 双向光衰 | `SAMPLE_REQUIRED` | 固定 `NOT_VERIFIED / REAL_DEVICE_SAMPLE_REQUIRED` |
| 配置下发 | `UNSUPPORTED` | Adapter 与 Guard 只允许只读命令 |

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

## 阶段二清单

取得真实 ZTE 节点后，按 Artifact 逐项完成：

1. SSH 登录和提示符验证。
2. `enable 15`、权限提示和只读账号能力验证。
3. 分页提示、空格续页和长输出终止行为验证。
4. `show version` 实际输出采样。
5. 接口摘要和详情输出采样。
6. `show opticalinfo` 摘要和详情输出采样。
7. 七条 LLDP 候选命令探测并确定正式命令。
8. LLDP Parser、无邻居、禁用和不支持语义校准。
9. AP 实际匹配和歧义处理验证。
10. DOM 字段、状态和门限语义校准。
11. 单端光功率和双端光衰计算验证。
12. 不同软件版本和 ZXR10 型号兼容验证。

阶段二只使用脱敏真实 Artifact 补充 fixture 和 Parser，不使用编造输出作为验证证据。
