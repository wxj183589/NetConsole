# Phase 8 凭据迁移验收

状态：PARTIAL

设备业务数据库随 DataRoot 复制，迁移报告明确记录凭据数据库复制状态。Windows DPAPI 密文仍绑定原 Windows 用户上下文，跨用户或跨计算机不能凭复制密文宣称迁移成功。报告将该状态标记为 `requires_origin_windows_user_context_or_reentry`，普通业务数据迁移不会因凭据不可解密而整体失败。

外部 SSH 终端 Provider 已支持根据设置传递用户名、密码或客户端会话参数，命令参数使用结构化 argv。真实 SecureCRT、PuTTY、Xshell 和 OpenSSH 启动及认证：NOT VERIFIED。测试凭据未写入日志或仓库。

同一 Windows 用户/计算机 DPAPI 继续可用性和跨计算机受密码保护迁移包：NOT VERIFIED。
