# 包内静态资源

本目录保存随 Python 包分发的开源说明、第三方组件资料和许可证。资源只读，不承载运行日志、数据库、真实配置或用户报告。

资源通过打包配置和资源 helper 定位；修改文件名或清单时运行许可证/SBOM 与 PyInstaller 资源测试，并检查相对路径。


## 用途与边界

本目录保存随 Python 包分发的只读开源说明、第三方组件资料和许可证；不保存用户配置、日志、数据库、采集结果或正式报告。

## 主要入口

许可证集中在 `licenses/`，第三方说明与开源 notice 位于当前目录的 Markdown/JSON 文件；构建通过包资源和制品清单引用。

## 依赖关系

发布脚本、PyInstaller 和开源说明服务消费这里的资源；文件名与 `pyproject.toml`、构建清单和打包 Guard 必须一致。

## 数据与状态

文件是版本化静态输入，不记录运行状态；最终制品可以复制只读资源，但运行数据仍写入系统应用数据目录。

## 测试与修改

修改许可证、notice 或资源路径时运行 license/SBOM、PyInstaller artifact 和 open-source notice 测试，并核对来源与版本。

## 生成与清理

构建复制属于制品生成，不在此生成临时文件；dist/build 临时输出按构建脚本清理，许可证原文不得被清理任务误删。

## 相关文档

参见 [第三方依赖](../../../docs/release/THIRD_PARTY_DEPENDENCIES.md)、[构建与发布](../../../docs/release/BUILD_AND_RELEASE.md) 和 `licenses/README.md`。
