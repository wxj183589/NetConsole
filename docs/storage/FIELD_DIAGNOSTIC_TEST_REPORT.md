# 现场诊断包测试报告

## 覆盖范围

- 临时目录、空目录和不存在的 Windows CIM/RAID 工具。
- Raw/日志大小与条数限制、metadata-only 文件扫描。
- allowlist 脱敏、部分 section 不可用、取消点和 ZIP 完整性。
- Export Worker 注册及 System Maintenance 请求参数校验。

## 未覆盖

本地环境未连接 Windows Server 2016、真实 RAID6 HDD、Ground ACTIVE 或生产数据根；未访问 `D:\NetConsoleData`。现场磁盘映射和性能计数器需主机集成验证。
