# NetConsole 桌面版

NetConsole 是一个面向网络设备运维的本地 Windows 桌面工具，使用 PySide6 构建界面，使用 SQLite 保存本地站点数据。项目当前重点覆盖设备管理、AC 管理、配置采集、文件管理、轨道交通业务、MESH 日志分析、车载 MR 在线收集和网络工具。

## 运行环境

- Windows 10 / Windows 11
- Python 3.13
- PowerShell
- 本地 SQLite 数据库

部分功能依赖外部工具或系统能力：

- `tools/fping_v3/Fping_v3.exe`：车载 MR 高频 Ping 采集
- `tools/iperf/iperf3.exe`：IPERF 带宽测试
- Windows WLAN API / `netsh`：无线扫描
- Netmiko：SSH / Telnet 设备连接

## 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 启动程序

```powershell
python main.py
```

也可以使用开发脚本：

```powershell
.\project\scripts\dev_run.ps1
```

## 运行测试

```powershell
pytest
```

也可以使用测试脚本：

```powershell
.\project\scripts\test.ps1
```

## 数据目录

开发环境和便携发布版本默认使用项目本地 `data/` 目录保存数据。

```text
data/
  sites/
    demo/
      db/
        devices.db
      raw/
      parsed/
      reports/
      backups/
      tasks/
      metrics/
```

`demo` 站点的主数据库路径为：

```text
data/sites/demo/db/devices.db
```

如果该数据库不存在，程序会自动创建最新表结构并写入演示设备数据。如果数据库已经存在，程序会直接使用现有数据，不会强制覆盖用户数据。开发测试时如需重新生成演示数据，可以删除 `data/sites/demo/db/devices.db` 后重新启动程序。

## 主要功能

### 设备管理

- 设备列表、搜索、筛选、分组管理
- 设备新增、编辑、删除
- SSH / Telnet 连接测试
- 设备详情查看
- H3C 设备详情刷新
- 诊断下载
- CSV 导入、导出和模板导出

设备支持 SSH 和 Telnet 独立启用。连接测试和设备详情刷新优先使用 SSH；如果未启用 SSH，则使用 Telnet。SNMPv1、SNMPv2c、SNMPv3 配置作为设备属性保存。

### AC 管理

- AC 资源采集
- FAT-AP / FIT-AP 资源展示
- AP 详情窗口
- 光模块诊断和历史记录
- AC 网页打开
- 日志解析和任务失败提示

### 配置采集中心

- 运行配置采集
- 已保存配置采集
- 保存配置归档
- 快照管理
- 配置差异对比
- 批量采集和任务进度显示

### 文件管理

- 类 WinSCP 双栏文件管理
- 设备文件下载
- 本地目录打开
- 设备名称目录规则
- MESH 日志快速选择

### 轨道交通

轨道交通模块包含以下功能：

- 轨旁AP业务
- MESH日志分析
- 车载MR在线收集

轨旁AP业务支持轨旁 AP 数据展示、光衰采集更新、接口历史弹窗和 AP 详情跳转。内部连接字段仅用于后台采集，不在主表和默认导出中展示。

MESH日志分析支持本地历史 MESH 日志导入、长期保存、按车载 MR 独立管理、主链路切换分析、Peer 趋势窗口、连续运行时段分析和 Excel 分析报告导出。

车载MR在线收集支持对车载 MR / FAT-AP 进行长连接采集，实时收集 MESH 主链路、信道繁忙度、AP 射频统计、切换历史、接口速率、高频 Ping 和 IPERF 打流数据。

### 网络工具

网络工具模块包含：

- IPERF 带宽测试
- 无线扫描

IPERF 页面用于执行带宽测试并展示服务端状态。无线扫描用于轨旁 AP 场景，支持 Windows WLAN API 与 netsh 混合扫描：Windows WLAN API 提供频宽、MIMO、RSSI、频率、信道和 IE 能力信息；netsh 补充 SSID、认证方式和加密方式；最终按 BSSID 合并为一条完整记录。

## 无线扫描说明

无线扫描支持四种扫描源：

- 自动
- 混合模式
- Windows WLAN API
- netsh 后备

默认使用自动模式，优先执行混合扫描。混合模式会同时获取 Windows WLAN API 和 netsh 结果，并按标准化 BSSID 合并。

字段来源规则：

- 频宽、MIMO：优先来自 Windows WLAN API 的 Beacon / Probe Response IE 解析
- RSSI、频率、信道：优先来自 Windows WLAN API
- SSID、认证方式、加密方式：优先来自 netsh
- 轨旁 AP 反查：在 BSSID 合并后执行

如果无线网卡驱动或 Windows API 未返回 IE blob，频宽和 MIMO 可能显示为 `-`。如果 netsh 失败，认证和加密字段可能显示为 `-`。

## 更新日志

程序内置更新日志文件：

```text
netconsole/docs/changelog.md
```

中文界面下更新日志窗口读取中文内容，标题格式为：

```text
更新日志 v1.2.0
```

后续更新版本时，应优先维护该中文更新日志源，避免只在 UI 层临时替换文字。

## 打包发布

发布脚本：

```powershell
.\build_release.bat
```

发布流程会调用：

```powershell
python project\release.py
```

自动发布脚本会更新版本文件、执行 git 提交、打标签并推送远端。自动提交说明已经统一为中文，例如：

```text
自动发布：更新版本、更新日志与构建文件
```

发布包会把运行时工具放入：

```text
_internal/tools/
```

其中包括：

```text
_internal/tools/fping_v3/Fping_v3.exe
_internal/tools/iperf/iperf3.exe
```

## 手工验证：连接测试

1. 启动 NetConsole。
2. 打开“设备管理”。
3. 选择演示设备 `AC`、`SW01` 或 `SW02`。
4. 点击“测试连接”。
5. 确认弹窗展示协议、地址、提示符和耗时。

演示设备示例：

```text
AC    10.0.0.51    admin / Admin@123
SW01  10.0.0.52    admin / Admin@123
SW02  10.0.0.53    admin / Admin@123
```

自动测试使用 mocked Netmiko 连接，不会连接这些演示地址。

## 手工验证：H3C 设备详情刷新

1. 启动 NetConsole。
2. 打开 `demo` 站点。
3. 进入“设备管理”。
4. 打开 AC、SW01 或 SW02 的设备详情。
5. 点击“刷新”。
6. 确认概览、接口、光模块和 LLDP 邻居数据刷新。
7. 确认原始日志生成在：

```text
data/sites/<site>/raw/collect/<collect_run_uuid>/<device_uuid>.log
data/sites/<site>/raw/collect/<collect_run_uuid>/<device_uuid>_commands.jsonl
```

H3C 详情刷新常用命令：

```text
screen-length disable
display current-configuration | in sysname
display version
display device
display device manuinfo
display boot-loader
display interface
display transceiver interface
display transceiver diagnosis interface
display lldp neighbor-information list
display lldp neighbor-information verbose
```

单条命令失败会写入日志，后续命令继续执行。

## 开发注意事项

- 不要提交本地临时文件、测试压缩包或个人 IDE 状态文件。
- 更新用户可见功能时同步更新 `netconsole/docs/changelog.md`。
- 后续 git commit message 使用中文，技术名词可以保留英文。
- 修改数据库结构时必须提供幂等迁移。
- 修改 UI 时应补充 PySide6 相关测试或服务层测试。
- 提交前至少运行相关测试；大范围改动应运行完整 `pytest`。
