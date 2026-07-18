# Python 源码目录

## 用途

本目录采用 `src` 布局，保存可安装的 NetConsole Python 包。

## 边界

只允许放 Python 包源码；不得写入数据库、日志、缓存、构建产物或虚拟环境。运行数据通过 `PathResolver` 写入开发数据根或系统应用数据目录。

## 主要入口

- `netconsole/`：Python Core、FastAPI、Application Service、Repository、Parser 和只读版本化资源。

## 依赖关系

应用入口、后台 Worker 和测试导入 `netconsole` 包。本目录不得依赖仓库当前工作目录或通过临时 `sys.path` 修复导入。

## 数据与状态

本目录自身不保存运行状态；包内资源必须只读并通过资源 helper 定位。

## 测试

对应测试位于 `../tests/`，使用项目虚拟环境运行 `python -m pytest`。

## 修改规则

新增顶层 Python 包前先更新仓库目录规范；框架、业务和基础设施依赖遵循项目架构边界。

## 生成与清理

`__pycache__/` 等缓存不纳入 Git，可安全重新生成。

## 相关文档

- [仓库目录规范](../docs/development/repository-layout.md)
- [架构](../docs/ARCHITECTURE.md)
