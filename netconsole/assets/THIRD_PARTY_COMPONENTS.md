# NetConsole 第三方组件说明

发布包使用 Python、PySide6、PySide6-Fluent-Widgets、openpyxl、XlsxWriter、Netmiko、Paramiko、PySNMP 等第三方组件。组件名称、用途和许可证标识见同目录 `open_source_notices.json`。

IPOP v4.1 是由用户手动请求管理员权限启动的独立外部工具。NetConsole 不自动启动、不修改、不在后台自动运行，也不在主程序退出时结束它。仓库没有 IPOP LICENSE/NOTICE，授权状态为“需用户确认再分发授权”；对外发布前必须补齐许可或移除二进制。普通开源包、内部包和客户包默认不内置 `IPOP.EXE`。

完整 IPOP 说明见同目录 `IPOP_v4.1_notice.md`。
