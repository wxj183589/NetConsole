# 主机密钥信任

正式信任事实源为 `PathResolver.global_known_hosts_path`，即数据根下的 `config/global/security/known_hosts`。该文件不随单局点导出包导出，不写仓库，不要求管理员修改 `%USERPROFILE%\\.ssh\\known_hosts`。

写入使用已有原子写入和锁文件机制；未知密钥仅在当前进程内保存挑战和 Paramiko key 对象，挑战过期后失效。已保存密钥变化时连接直接阻止，不能普通一键绕过。

跳板机按原始 `jump_host + jump_port` 管理，目标设备按原始 `target_host + target_port` 管理；经本地
转发时不得把目标记录为 `127.0.0.1:随机端口`。两端未知密钥分别返回
`DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN` 和 `DEVICE_FILE_TARGET_HOST_KEY_UNKNOWN`，密钥变化分别返回对应
`*_MISMATCH`，连接测试、设备操作与设备文件使用同一严格策略。

“仅本次信任”精确绑定主机、端口、算法和密钥字节。同一连接流程可以累积跳板机与目标设备两份授权，
确认后一端时不会丢失前一端的授权，也不会把授权扩大到其他地址或端口。

API 只返回设备名、主机、端口、算法和 SHA256 指纹，不返回服务器绝对路径、密钥字节或凭据。
