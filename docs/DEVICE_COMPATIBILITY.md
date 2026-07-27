# 设备版本兼容性基线

NetConsole 使用代码内登记的设备兼容性基线描述当前适配范围。基线文件为 `resources/device_compatibility_profiles.json`，由 `src/netconsole/services/device_compatibility/` 加载、校验和解析。

## 运行时边界

- Dashboard 只读取代码内置兼容基线摘要，不扫描用户本地数据库。
- 正常启动、首页打开、局点切换、设备管理打开和定时任务均不会执行兼容性扫描。
- 未登记的设备型号或软件版本进入安全降级；不得把 V5 当 V7、老 V7 当新 V7、V9 当 V7。
- Vue 页面不判断 Comware 版本，也不提交原始 CLI 文本。

## 开发期扫描

开发人员需要发现新型号或新 Release 时，手动执行：

```powershell
.venv/Scripts/python.exe scripts/scan_local_device_compatibility.py --report-only
```

该工具只读取本地已有设备资料和历史结构化采集结果，默认生成脱敏候选报告到数据根 `temp/compatibility/`。候选报告不包含局点名称、设备名称、管理 IP、MAC、序列号、用户名、密码、Token、完整配置、完整 BootROM 原文或原始业务日志。

`--apply` 当前保持关闭；新增兼容配置必须先人工确认 `command_profile_id`、`parser_profile_id`、能力矩阵、验证等级和脱敏 fixture，再通过代码评审写入兼容目录。

## 当前状态

当前基线登记 H3C Comware V7/V9 的无线控制器、交换机和车载 MR 方向，并增加 ZTE ZXR10 5960X-ES V2 轨旁 AP 接入交换机能力。登记状态不等于所有型号和 Release 已完成现场验证；V5 仅保留未来扩展空间，本次未登记为已适配，也未实现 V5 命令或解析器。

| 厂商 / 类型 | 当前支持 | 当前边界 |
| --- | --- | --- |
| H3C | 保持既有 Comware 设备管理、采集和导入导出范围 | 具体型号、Release 与真实设备状态仍以版本化 Profile 和 fixture 为准 |
| ZTE ZXR10 5960X-ES V2 / SW | 设备模型、只读 SSH 框架、命令 Profile、接口/DOM 文档样例 Parser、厂商采样 Job 和轨旁 AP 页面入口 | `show version`、接口和 DOM 仅为 `DOCUMENT_SAMPLE_ONLY`；LLDP 候选只进入独立采样任务并保持 `SAMPLE_REQUIRED`；AP 关联和双向光衰均待真实节点验证 |
| ZTE / AC | 不支持 | 导入和写入返回“当前版本尚未适配 ZTE 无线控制器” |
| ZTE 诊断包 | 不支持 | 不猜测 `display diagnostic-information` 等价命令，不向 ZTE 发送 H3C 诊断命令 |

ZTE 不代表“全系列完全适配”。本阶段没有连接真实节点，不支持 ZTE 配置下发、配置采集中心、文件管理、CLI Ping、完整诊断包或 ZTE AC。不得下发未经资料确认的分页关闭命令；`--More--` 仅由通用 SSH 分页执行器在模拟测试中验证受控处理框架。

`show opticalinfo` 文档样例中的 Rx/Tx 只用于 Parser 测试，不保存为现场业务数据。ZTE 行第一阶段固定返回 `NOT_VERIFIED / REAL_DEVICE_SAMPLE_REQUIRED`，不计算正向或反向光衰；H3C 保持既有两端 DOM 计算规则。

命令来源仍以 `resources/device_command_profiles.json`、命令说明和后端受控命令 Guard 为准。任何新增兼容配置不得引入删除网络设备、重启网络设备、恢复出厂、清空配置、格式化存储或任意 CLI 执行入口。
