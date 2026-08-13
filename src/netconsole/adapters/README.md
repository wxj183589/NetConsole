# 设备适配器

本目录把外部设备/协议差异适配为 Core 可用的连接与命令数据，当前重点是 H3C/Comware。适配器不承担 UI、数据库或页面状态机。

主要实现位于 `h3c/`；依赖解析器、Netmiko 和编码工具。修改设备回显或命令适配后运行 adapter/parser 定向测试，并保留原始文本语义。

## 用途与边界

本目录把 H3C/Comware 等外部设备差异适配为 Core 可用的连接和命令数据；不负责 Router、Vue、Repository 或用户可见状态机。

## 主要入口

`h3c/` 是当前设备适配入口，命令 profile、接口/LLDP/光模块解析和通用 parser 在其下维护。

## 依赖关系

适配器依赖 Netmiko、文本编码规则和 `parsers/`，由 Service/Application 调用；它不能反向依赖 Web/Electron。

## 数据与状态

输入是设备会话回显和受控命令参数，输出是内存结构或 Service 需要的结果；原始文本、数据库和日志由上层路径/任务管理。

## 测试与修改

运行 H3C adapter/parser、编码和设备 Service 定向测试。修改命令、顺序、正则或字段时必须保留原始文本语义并检查下游消费者。

## 生成与清理

适配器不生成持久文件；采集原始日志和临时解析结果由 Job/PathResolver 写入运行数据根，测试产物使用临时目录并按 fixture 清理。

## 相关文档

参见 [命令参考](../../../docs/device-management/COMMAND_REFERENCE.md)、[编码规则](../../../docs/DEVELOPMENT_RULES.md) 和 `h3c/README.md`。
