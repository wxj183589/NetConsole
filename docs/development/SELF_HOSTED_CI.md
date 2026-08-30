# GitHub Actions / Self-hosted CI 退役说明

NetConsole 已退役 GitHub Actions 及仓库 `.github` 配置。本文只保留当前验证边界，不再定义 Hosted Runner、Self-hosted Runner、Workflow 或 Required Check 的配置。

## 当前验证权威

- 主机/副机本地定向测试；
- 主机集成验证；
- 必要的真实 `D:\NetConsoleData-dev` 验收；
- Release Gate。

本地 Gate 的风险分层、消费者套件和隔离测试根见 [Change Impact Framework](./CHANGE_IMPACT_FRAMEWORK.md) 与 [测试基线](../testing/BASELINE.md)。真实 GUI、设备、安装包和长时运行验收仍需单独记录，不由自动化结果替代。
