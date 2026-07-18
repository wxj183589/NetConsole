# Feature Profile 配置

本目录保存按客户/场景划分的功能开关 profile。它描述可审查的默认启用集合，不取代代码中的 Feature Registry，也不承载用户运行时设置。

主要入口在 `features/`；修改 profile 后运行功能开关与页面导航测试，检查新增 key 已在注册表登记。

## 用途与边界

本目录保存按客户/场景划分的静态 Feature profile，不替代 Feature Registry，也不承载用户运行时设置、设备数据或凭据。

## 主要入口

`features/customer.json` 和 `features/full.json` 是当前 profile 示例；文件名和 schema 由配置加载方约束。

## 依赖关系

Profile key 必须来自 `src/netconsole/core/feature_registry.py`，并由启动/构建配置和 Web 导航/FeatureGate 消费。

## 数据与状态

文件表示默认能力集合，运行时可能叠加用户/环境开关；真实状态写入应用数据目录，不修改仓库模板。

## 测试与修改

新增或修改 key 前运行 Feature、导航和配置校验测试，检查默认可见/启用状态与用户可见文本。

## 生成与清理

profile 不生成运行数据；测试生成的合并配置写入临时目录，不能覆盖模板或提交缓存。

## 相关文档

参见 [功能模块](../../docs/FEATURE_MODULES.md) 和 [仓库目录规范](../../docs/development/repository-layout.md)。
