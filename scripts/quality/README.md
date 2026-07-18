# 质量门禁脚本

本目录保存不改变业务行为的仓库质量检查器，当前入口是目录 README 覆盖检查。检查器只以 `git ls-files` 的跟踪路径构造维护目录集合，避免把本地依赖、构建物和其他 Worker 的未跟踪源码纳入基线。

从仓库根运行 `python -m scripts.quality.check_directory_readmes`；失败时按稳定排序输出缺失目录并返回非零码。修改规则后运行 `tests/quality/`、Ruff、`py_compile` 和文档链接测试。

## 用途与边界

这里维护仓库质量门禁，不参与产品运行。当前检查目录 README 覆盖、固定排除类别和重大目录的结构化小节。

## 主要入口

`check_directory_readmes.py` 可从仓库根按 Python module 运行；`tests/quality/test_directory_readmes.py` 覆盖分类、排序、结构和退出码。

## 依赖关系

检查器依赖 Git 的 `ls-files` 输出和 Python 标准库；它不扫描 node_modules、构建目录、未跟踪源码或读取设备/数据库。

## 数据与状态

检查只读取 Git 跟踪路径和现有 README 文本，输出稳定的缺失目录/小节诊断，不修改索引、工作树或运行数据。

## 测试与修改

修改排除/重大目录规则必须增加合成路径测试，并运行质量测试、项目 Markdown 链接测试、Ruff 和 py_compile。

## 生成与清理

检查器不生成业务产物；pytest/py_compile 的缓存由项目忽略规则处理，不得把质量报告或缓存提交到仓库。

## 相关文档

参见 [仓库目录规范](../../docs/development/repository-layout.md)、[项目文档索引](../../docs/README.md) 和 `tests/quality/README.md`。
