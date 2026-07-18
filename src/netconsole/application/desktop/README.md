# Desktop Application Actions

本目录定义 Electron Desktop 允许调用的本机动作应用边界，把白名单文件选择、Artifact、终端/通知等动作交给受控基础设施。它不提供任意命令或路径执行。

主要入口为 `actions.py`；依赖 Feature Gate、PathResolver 和 Desktop infrastructure。修改后运行 Desktop action、Bridge 和安全测试。
