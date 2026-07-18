# 版本化配置

本目录保存可审查、可提交的构建与功能配置模板，不放真实账号、Token、community、私钥或生产局点数据。运行配置由应用数据目录承载。

当前主要入口是 `profiles/` 和 PyInstaller 依赖许可清单。修改配置后运行对应 Guard/测试，确认路径、Feature key 和敏感信息边界。

## 用途与边界

本目录只保存可审查、可提交的构建/功能配置模板，不保存真实账号、Token、community、私钥或生产局点数据；用户运行配置属于应用数据目录。

## 主要入口

`profiles/` 提供 Feature profile，`pyinstaller-approved-distributions.json` 为构建依赖审计清单。

## 依赖关系

Profile 由 Feature Registry/启动配置消费，构建清单由 `scripts/build` 的制品和许可证 Guard 消费；配置不能绕过 Service、PathResolver 或安全校验。

## 数据与状态

仓库配置是版本化静态输入；用户实际设置、凭据和局点数据进入系统应用数据根，不回写本目录。

## 测试与修改

修改 key、默认值或构建清单时运行 Feature、依赖、许可证和打包测试，并核对对应 docs。配置字段要有明确消费者和脱敏样例。

## 生成与清理

本目录不生成运行数据；构建读取配置产生的 dist/build 临时物必须写忽略目录，结束后由构建脚本清理。

## 相关文档

参见 [仓库目录规范](../docs/development/repository-layout.md)、[功能模块](../docs/FEATURE_MODULES.md) 和 [构建与发布](../docs/BUILD_AND_RELEASE.md)。
