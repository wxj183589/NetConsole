# fping

本目录是版本化的 Windows x64 `fping.exe` 和同版本 `cygwin1.dll` 源资源。Agent 交付包会把它复制到 `tools/windows-x64/fping/`；真实 `fping` 任务只读取配置指定的交付目录，不依赖系统 PATH；启动前会验证版本、JSON 输出和源地址参数支持。

`ping_probe` 是独立的 TCP Connect 探测，不依赖 fping，也不等同于 ICMP Ping。
