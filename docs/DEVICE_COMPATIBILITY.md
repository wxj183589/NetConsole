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

当前基线登记 H3C Comware V7/V9 的无线控制器、交换机和车载 MR（Cloud AP）方向。登记状态不等于所有型号和 Release 已完成现场验证；V5 仅保留未来扩展空间，本次未登记为已适配，也未实现 V5 命令或解析器。

命令来源仍以 `resources/device_command_profiles.json`、命令说明和后端受控命令 Guard 为准。任何新增兼容配置不得引入删除网络设备、重启网络设备、恢复出厂、清空配置、格式化存储或任意 CLI 执行入口。
