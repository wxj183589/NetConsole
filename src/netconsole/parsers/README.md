# 设备与日志解析器

本目录把 H3C/Comware 回显、FIT-AP、Mesh 等原始文本解析为业务结构，保持原始命令顺序和可诊断错误。解析器不建立连接、不写数据库、不渲染 UI。

主要子目录为 `h3c/`；编码按项目的 utf-8-sig、utf-8、gb18030、gbk 规则处理。修改字段或容错时运行 parser fixture 与领域测试。


## 用途与边界

本目录将 H3C/Comware、FIT-AP 和 Mesh 原始文本解析为稳定业务结构，保留可诊断的原始语义；不建立设备连接、不写数据库、不渲染 UI。

## 主要入口

`h3c/` 是设备基础与 AC/FIT-AP parser 入口；顶层模块提供跨域文本/日志解析，调用方通过明确函数传入原始文本。

## 依赖关系

解析器依赖纯 Python 标准库、编码工具和脱敏 fixture，被 Adapter、Service、Job 和离线分析调用；不得依赖 Router 或 Vue。

## 数据与状态

输入是外部回显/原始日志，输出是内存模型或可序列化记录；原始文件的读写、数据库保存和任务状态由上层 Service/Repository 管理。

## 测试与修改

运行 H3C/Mesh parser、编码、AC/设备 Service 定向测试。修改正则、列边界、命令顺序或容错时同步字段消费者并保留 fixture 证据。

## 生成与清理

解析器不直接生成持久文件；离线导入的 parsed 数据和报告由 Job/PathResolver/Export 管理，测试输出写临时目录并自动清理。

## 相关文档

参见 [命令参考](../../../docs/device-management/COMMAND_REFERENCE.md)、[编码规则](../../../docs/DEVELOPMENT_RULES.md) 和 `h3c/README.md`。
