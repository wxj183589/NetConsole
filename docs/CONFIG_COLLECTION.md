# 配置采集与快照对比

## 功能与入口

Electron 页面 `/config-collection` 负责 H3C/Comware 配置采集、保存配置、快照查看、双文件对比和导出。Vue 只提交设备或快照 ID；设备连接、配置命令、文件读取、差异计算、删除回滚和导出均由 Python Application Service、Job Center 与 Export Process 执行。

状态为 `IMPLEMENTED_UNVERIFIED`：自动化已覆盖页面选择、任务、差异和 Artifact 契约，但尚不能替代真实设备采集、桌面文件保存和大配置人工验收。

## 快照与选择规则

- `running`、`saved` 和 `diff` 是独立快照类型；切换设备或类型会清空当前表格勾选，避免复用不可见的旧选择。
- 勾选恰好两条快照时，当前勾选直接成为可见的左右对比对；也可用“设为左侧/右侧”跨设备保留两个手工选择。
- 勾选一条时不能启动对比；勾选超过两条时对比与差异导出禁用，但批量 ZIP 导出和删除仍可使用全部勾选项。
- 左右快照 ID 相同视为无效。不同设备允许对比，标题必须显示“设备名 · 类型 · 时间”，不能只显示文件名。

## 对比流程

`config_compare_snapshot_pair` Job 按快照 ID 在当前数据根内解析安全文件引用，读取文本并返回统一 Diff 行。页面在同页显示左行号、左文本、状态、右行号和右文本，支持全部/新增/删除/修改过滤以及上一处、下一处差异导航。左侧设备树可收起；代码区和差异区独立滚动，不挤压页面。

空文件必须作为真实空内容处理；两个相同文件返回零处差异；跨设备文件保持各自标签。文件缺失、引用越界、读取失败或快照不属于当前局点时任务失败，不回退到任意本机路径。

配置正文的业务裁剪由 Python `extract_h3c_configuration_body()` 完成。当前实现清理设备文本后，从首个独立 `#` 截取到最后一个 `return`（包含两端）；找不到完整边界时走 fallback 清理。它没有实现“从 `display version` 到末尾最后一个 `#` 前”的规则。若该规则仍是产品要求，需要修改服务与 fixture，不能只改 Vue 或文档。修改时必须覆盖空文本、相同文本、尾部提示符和多段 `#`。

当前页面使用设备表、快照表和结果卡片布局，没有“左侧树收起”控件；结果区和代码区已有滚动。左侧树收起属于尚未实现的交互，不得写成已上线。

## 安全、恢复与导出

- 前端不提交设备命令、密码、服务端路径或任意文件路径；`save force` 走独立计划/确认链路。
- 采集、读取和对比使用普通 Job；ZIP 与差异文件使用 Export Process，临时文件完成后原子提交。
- 删除先把文件移入受控隔离区，再更新数据库；数据库失败必须恢复文件。确认 Token 有局点、摘要和有效期约束，不写日志。
- 页面重载后从 Task API 恢复活动任务；关闭页面不停止后台任务。原始回显、快照和 Artifact 仍由 `PathResolver` 管理。

## 验收

定向检查至少包括：两条勾选可对比、跨设备手工左右选择、设备/类型切换清空勾选、超过两条只影响对比、空/相同/不同文件、裁剪边界、双栏导航、导出、删除回滚、取消与恢复。

相关路径：

- `apps/web/src/views/config-collection/`
- `src/netconsole/services/config_collection_web_service.py`
- `src/netconsole/services/config_lifecycle_service.py`
- `src/netconsole/services/job_center/handlers/config_jobs.py`
- `tests/test_config_collection_web_api.py`
- `apps/web/src/views/config-collection/ConfigCollectionView.test.ts`

提交 `631a52e1` 修复了“两条已勾选快照未成为实际对比输入”的状态问题。`display version -> 末尾 #` 裁剪和左树收起仍未实现；真实设备与 Electron 人工验收完成前不得提升为 `COMPLETE`。
