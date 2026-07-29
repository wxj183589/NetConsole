# Native Helper 源码

本目录保存 Electron Desktop 构建使用的本机 helper 源码。当前 `elevated-launcher/` 提供受固定 JSON 契约约束的 Windows 管理员启动 helper。

本目录不实现 Renderer、设备访问、数据库或 Python 业务逻辑；生成的 native 可执行文件属于构建产物。
