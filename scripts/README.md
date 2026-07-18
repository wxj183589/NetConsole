# 项目脚本

本目录按 `build/`、`dev/`、`maintenance/`、`quality/`、`architecture/` 和 `ui/` 分组保存构建、开发 smoke、维护与门禁脚本。脚本应从自身位置或统一项目根定位资源，不依赖调用者当前目录，也不实现 UI 业务。

修改脚本后使用 `python -m scripts.<group>.<module>` 或项目规定的 PowerShell 入口验证；临时输出写入 `.local/`、`dist/` 或测试临时目录并按规则清理。

## 用途与边界

本目录按 build、dev、maintenance、quality 分组保存工程脚本；脚本不承载 Web/UI 业务，不得通过当前工作目录或临时 sys.path 访问源码。

## 主要入口

`build/` 负责编译发布，`dev/` 负责本地 smoke，`maintenance/` 负责迁移/审计，`quality/` 负责仓库门禁，`architecture/` 负责 Electron-only 分层门禁，`ui/` 负责表格和字段展示契约；模块均可按 Python module 方式运行。

## 依赖关系

脚本依赖项目虚拟环境、`src/netconsole`、构建配置和显式项目根；输出规则由 `docs/development/repository-layout.md`、质量 Guard 和各脚本 README 约束。

## 数据与状态

脚本读取版本化源码/配置，运行数据、日志、数据库和报告必须进入 `.local/`、系统应用数据目录、dist 或测试临时目录。

## 测试与修改

修改脚本后运行对应 Python 测试、Ruff、py_compile 和必要的构建/链接检查；保持 Windows PowerShell 编码和路径行为可复现。

## 生成与清理

构建物、SBOM、临时报告和缓存按脚本白名单生成；结束后使用现有清理脚本，不递归删除未知的用户数据、会话或正式报告。

## 相关文档

参见 [构建与发布](../docs/BUILD_AND_RELEASE.md)、[仓库目录规范](../docs/development/repository-layout.md) 和子目录 README。
