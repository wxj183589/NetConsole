# 配置采集与快照对比

## 功能与入口

Electron 页面 `/config-center` 负责 H3C/Comware 配置采集、保存配置、快照查看、双文件对比和导出。Vue 只提交设备或快照 ID；设备连接、配置命令、文件读取、差异计算、删除回滚和导出均由 Python Application Service、Job Center 与 Export Process 执行。

状态为 `IMPLEMENTED_UNVERIFIED`：自动化已覆盖页面选择、任务、差异、Monaco 生命周期和 Artifact 契约，但尚不能替代真实设备采集、桌面文件保存、Electron 离线运行和大配置人工验收。

## 快照与选择规则

- `running`、`saved` 和 `diff` 是独立快照类型；切换设备或类型会清空当前表格勾选，避免复用不可见的旧选择。
- 设备列表默认只显示 `work_scope_status=included`；切换“包含暂不参与”后可查看 `excluded` 设备，用户按设备 ID 明确选择时仍允许手动只读采集。
- 勾选恰好两条快照时，当前勾选直接成为可见的左右对比对；也可用“设为左侧/右侧”跨设备保留两个手工选择。
- 勾选一条时不能启动对比；勾选超过两条时对比与差异导出禁用，但批量 ZIP 导出和删除仍可使用全部勾选项。
- 左右快照 ID 相同视为无效。不同设备允许对比，标题必须显示“设备名 · 类型 · 时间”，不能只显示文件名。

## 对比流程

`config_compare_snapshot_pair` Job 按快照 ID 在当前数据根内解析安全文件引用，读取文本并计算完整差异。Worker 终态返回有界的 `left_text`、`right_text`、`diff_rows`、`raw_diff` 预览，以及完整 `diff_summary`、原始长度、行总数、截断/省略标记和左右标签；完整统一 Diff 写入受管 `.diff` Artifact，左右完整配置仍通过各自快照 Artifact 下载。页面默认使用只读 Monaco Diff Editor 展示终态预览；“差异明细”保留当前预览内的左行号、左文本、状态、右行号和右文本，并支持全部/新增/删除/修改过滤。上一处、下一处由当前返回的 `diff_rows` 生成目标，不使用 Monaco 内部命令作为业务事实。

结果使用显式的内容/差异状态，不以非空字符串判断任务是否有效。空文件作为真实空内容处理；两个相同文件返回零处差异并仍显示只读对比器；跨设备文件保持各自标签。文件缺失、引用越界、读取失败或快照不属于当前局点时任务失败，不回退到任意本机路径。

配置正文的业务裁剪由 Python `extract_h3c_configuration_body()` 完成。当前实现清理设备文本后，从首个独立 `#` 截取到最后一个 `return`（包含两端）；找不到完整边界时走 fallback 清理。它没有实现“从 `display version` 到末尾最后一个 `#` 前”的规则。若该规则仍是产品要求，需要修改服务与 fixture，不能只改 Vue 或文档。修改时必须覆盖空文本、相同文本、尾部提示符和多段 `#`。

当前页面使用设备表、快照表和结果卡片布局，没有“左侧树收起”控件；结果区和代码区已有滚动。左侧树收起属于尚未实现的交互，不得写成已上线。

## Monaco 展示边界

- 使用官方 `monaco-editor 0.56.0`，只注册随 Web 构建产物离线提供的基础 `editor.worker`；不打包 TypeScript、JSON、CSS 或 HTML Worker，不使用 CDN、远程 Worker、Blob URL 或 Electron Bridge。
- Monaco 和 Worker 加载器按需分块；没有合法差异结果时不加载、不创建 Editor。配置 Model 使用可追踪且不冲突的 `netconsole://config-diff/...` URI，语言固定为 `plaintext`。
- 编辑器固定 `readOnly` 和 `originalEditable: false`，支持并排/内联、自动换行、浅色/深色主题即时切换；主题更新不重建任务、全文或 Model。
- 新结果只在左右文本或比较身份变化时更新/替换 Model。清空结果、组件卸载和路由退出会释放 Editor、Model、差异订阅、主题监听和 `ResizeObserver`；KeepAlive 停用时暂停环境监听，激活后重新布局。
- Monaco 初始化或 Worker 加载失败时自动切到结构化差异明细，保留后台摘要、导航和 Artifact。Worker 预览按 JSON ASCII 转义后的字节预算截断，不能用提高 1 MiB 协议上限代替完整 Artifact；预览正文带截断说明，结果字段保留原始长度和省略数量。
- `diff_summary`、有界 `diff_rows/raw_diff` 预览和完整 Artifact 继续以 Python Job 结果为准；Monaco 自身的渲染差异不回写业务摘要，也不参与配置合规、保存、合并或下发。

## 安全、恢复与导出

- 前端不提交设备命令、密码、服务端路径或任意文件路径；Monaco 只消费任务结果中的安全文本和标签；`save force` 走独立计划/确认链路。
- 采集、读取和对比使用普通 Job；ZIP 与差异文件使用 Export Process，临时文件完成后原子提交。
- 用户主动导出配置差异或快照 ZIP 时，Electron 在创建 Export Task 前先选择最终路径；取消不创建任务。Artifact 完成后通过任务绑定写入预选路径，不再弹第二次窗口；保存失败保留 Artifact，可在 Task Center 重新选择位置而不重新生成。
- 单个已有配置 Artifact 和历史任务没有预绑定路径，只在用户点击下载/另存时打开一次 Save As。页面恢复历史任务不会自动弹窗。
- 删除先把文件移入受控隔离区，再更新数据库；数据库失败必须恢复文件。确认 Token 有局点、摘要和有效期约束，不写日志。
- 页面重载后从 Task API 恢复活动任务；关闭页面不停止后台任务。原始回显、快照和 Artifact 仍由 `PathResolver` 管理。

## 验收

定向检查至少包括：两条勾选可对比、跨设备手工左右选择、设备/类型切换清空勾选、超过两条只影响对比、空/相同/不同文件、裁剪边界、Monaco 并排/内联和换行、主题切换、结构化明细与导航、初始化失败/大文件降级、重复打开/清空后的资源释放、导出、删除回滚、取消与恢复。

相关路径：

- `apps/web/src/views/config-collection/`
- `apps/web/src/components/config-diff/ConfigDiffViewer.vue`
- `apps/web/src/components/config-diff/ConfigMonacoDiff.vue`
- `apps/web/src/views/config-collection/configDiffAdapter.ts`
- `apps/web/src/platform/monacoEnvironment.ts`
- `src/netconsole/services/config_collection_web_service.py`
- `src/netconsole/services/config_lifecycle_service.py`
- `src/netconsole/services/job_center/handlers/config_jobs.py`
- `tests/test_config_collection_web_api.py`
- `apps/web/src/views/config-collection/ConfigCollectionView.test.ts`

提交 `631a52e1` 修复了“两条已勾选快照未成为实际对比输入”的状态问题。`display version -> 末尾 #` 裁剪和左树收起仍未实现；真实设备、Electron 离线加载与大配置人工验收完成前不得提升为 `COMPLETE`。
