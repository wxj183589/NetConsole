# 质量门禁脚本

本目录保存不改变业务行为的仓库质量检查器，当前入口包括目录 README 覆盖检查和 Change Impact Audit。检查器只读取 Git 元数据、版本化配置和仓库文件，避免把本地依赖、构建物和其他 Worker 的未跟踪源码纳入基线。

从仓库根运行 `python -m scripts.quality.check_directory_readmes`；失败时按稳定排序输出缺失目录并返回非零码。修改规则后运行 `tests/quality/`、Ruff、`py_compile` 和文档链接测试。

运行 `python -m scripts.quality.check_change_impact --paths <路径...>` 可在编码前按计划路径输出 L1-L4、共享高风险区域、领域 owner、影响消费者、兼容性风险和最低回归套件。CI 使用 `--base-sha/--head-sha` 分析提交差异，并通过 `--github-output/--github-summary` 生成稳定输出；它不执行测试，也不能判断本地并行 worktree 所有权。

## 用途与边界

这里维护仓库质量门禁，不参与产品运行。当前检查目录 README 覆盖、固定排除类别、重大目录的结构化小节，以及共享层 Change Impact/Consumer Matrix。

## 主要入口

- `check_directory_readmes.py`：从仓库根按 Python module 运行；`tests/quality/test_directory_readmes.py` 覆盖分类、排序、结构和退出码。
- `check_change_impact.py`：读取 `config/architecture/change_impact_matrix.json`，按显式路径或 Git 提交范围输出最低风险等级与消费者套件。

## 依赖关系

检查器依赖 Git diff、版本化 JSON 和 Python 标准库；它不扫描 node_modules、构建目录、未跟踪源码或读取设备/数据库。

## 数据与状态

检查只读取 Git 跟踪路径、提交差异、现有 README 和影响矩阵，输出稳定诊断，不修改索引、工作树或运行数据。`--github-output/--github-summary` 只写 GitHub Actions 提供的临时协议文件。

## 测试与修改

修改排除/重大目录规则必须增加合成路径测试，并运行质量测试、项目 Markdown 链接测试、Ruff 和 py_compile。修改影响矩阵时还要分别用一个普通领域路径、一个 L3 路径和一个 L4 路径检查分类结果。

## 生成与清理

检查器不生成业务产物；pytest/py_compile 的缓存由项目忽略规则处理，不得把质量报告或缓存提交到仓库。

## 相关文档

参见 [仓库目录规范](../../docs/development/repository-layout.md)、[项目文档索引](../../docs/README.md) 和 `tests/quality/README.md`。
