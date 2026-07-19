# 主机密钥信任

正式信任事实源为 `PathResolver.global_known_hosts_path`，即数据根下的 `data/global/security/known_hosts`。该文件不随单局点导出包导出，不写仓库，不要求管理员修改 `%USERPROFILE%\\.ssh\\known_hosts`。

写入使用已有原子写入和锁文件机制；未知密钥仅在当前进程内保存挑战和 Paramiko key 对象，挑战过期后失效。已保存密钥变化时连接直接阻止，不能普通一键绕过。

API 只返回设备名、主机、端口、算法和 SHA256 指纹，不返回服务器绝对路径或凭据。
