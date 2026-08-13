# 版本化资源

本目录保存随代码发布的只读命令参考、设备命令 profile、分析规则、品牌资源和已审计运行工具。运行日志、数据库、采集结果和报告不得写回这里。

主要入口包括 `command_reference.json`、`device_command_profiles.json`、`mesh_quality_rules.json` 与 `tools/`。修改资源后运行相关 parser、构建清单和资源 Guard 测试。

## 用途与边界

本目录是随代码发布的只读资源边界，包含命令参考、设备命令 profile、分析规则、品牌资源和已审计工具；不保存运行日志、数据库、抓包或报告。

## 主要入口

命令资源为 `command_reference.json`/`device_command_profiles.json`，后者是正式执行的唯一 Profile 事实源。
`device.sftp.enable` 属于 `controlled_write`，必须由 Application Service、DeviceOperationService 和
Task Center 组成的受控链路调用；资源本身不是 Renderer、命令说明页或文件浏览器的执行白名单。
Mesh 规则为 `mesh_quality_rules.json`，运行工具来源位于 `tools/`。

## 依赖关系

Parser/Service 读取命令与分析规则，构建脚本读取品牌和工具元数据；资源定位必须通过包/项目 helper，不得使用 `Path.cwd()`。

## 数据与状态

资源文件是版本化静态输入；解析结果、任务状态和正式导出进入应用数据根或用户选择目录，不回写资源目录。

## 测试与修改

修改 schema、命令顺序、风险或阈值时运行 Parser、领域、许可证/SBOM 和运行工具 Guard 测试，并检查消费者。

## 生成与清理

构建只复制资源到受控制品目录；构建/打包输出和临时校验文件不留在 `resources/`，清理遵守发布白名单。

## 相关文档

参见 [命令参考规范](../docs/device-management/COMMAND_REFERENCE.md)、[构建与发布](../docs/release/BUILD_AND_RELEASE.md) 和 [资源工具说明](./tools/README.md)。
