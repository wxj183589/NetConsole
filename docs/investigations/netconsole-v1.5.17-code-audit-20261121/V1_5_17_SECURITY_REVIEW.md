# v1.5.17 安全复审

## 检查项

- 直接 SQL 架构检查：PASS；Repository 查询保持参数绑定，未发现新的 UI/Service 直连数据库入口。
- 设备命令硬编码检查：PASS；命令通过版本化 Profile/Capability 路由，未发现新增未登记写命令。
- 认证与 IPC：Electron 使用 context isolation、白名单 IPC 和会话令牌；Renderer 不持有长期凭据。
- 文件与数据根：Portable/安装版沿用 fail-closed 数据根和排他锁；任务与诊断输出使用受控目录。
- 敏感信息：源码中的 Demo 凭据仅属于显式 demo fixture/service，发布包不包含真实数据、原始 RAR、`.git`、node_modules 或 venv；包级 smoke 仍需在构建后验证。
- 维护脚本：本轮修复生命周期审计脚本的隐式 data-root 读取，要求显式路径确认。

## 风险边界

本轮未读取生产数据、真实设备或现场 RAR；未执行任何写入生产/开发 Authority 的动作。凭据加密、Windows Defender、真实网络暴露和人工安装安全性需要环境验收，不能由静态代码审查代替。
