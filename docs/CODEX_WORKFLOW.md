# Codex 工作流

本文档是后续 Codex 开发前的快速规则入口。

## 开始前

1. 阅读本文件和 [开发约定](DEVELOPMENT_CONVENTIONS.md)。
2. 涉及 UI、导出、网络、解析、大表、数据库、文件扫描或图表时，先阅读 [Renderer 响应性规范](ui_thread_policy.md)、[后台任务规范](background_task_policy.md)、[导出进程规范](export_process_policy.md)。
3. 明确本次任务范围、计划修改路径和验收标准，避免顺手重构。
4. 先用 `rg` 查找现有组件、服务、状态、调用者和测试。
5. 使用 [`change_impact_matrix.json`](../config/architecture/change_impact_matrix.json) 判断 L1-L4；计划路径可先运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.quality.check_change_impact --paths <计划修改路径...>
```

6. 优先使用项目 `.venv`：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

7. 文档任务原则上只改 Markdown / docs 文件，不改业务代码。

## Change Impact Audit

风险等级是最低等级；自动脚本只根据路径上调风险，无法识别同一文件中的语义扩张，开发者必须按真实改动主动上调，禁止把 L3/L4 拆成多个文件提交后按 L1/L2 报告。

| 等级 | 范围 | 最低验证 |
| --- | --- | --- |
| L1 | 单页面 CSS、文案、局部只读展示或纯文档 | 当前文件静态检查、定向 UI/文档检查、`git diff --check` |
| L2 | 单一领域 Service、Repository、Parser 或页面行为 | 当前领域的成功/失败/空数据契约与对应前后端测试 |
| L3 | 共享组件、Renderer API 基础、Task/Job、Export、AP Identity | 当前模块测试 + Consumer Matrix 指定的所有消费者套件 |
| L4 | Feature Registry、DataRoot、数据库迁移、Electron runtime、CI、构建发布 | L3 要求 + 完整集成/架构/制品门，并在合并后对 `main` 最终提交复验 |

以下区域默认为共享高风险文件，不因改动行数少而降级：

- `apps/desktop_renderer/src/api/client.ts`；
- `apps/desktop_renderer/src/components/table/`，尤其 `NcDataTable.vue`；
- `src/netconsole/core/feature_registry.py`；
- `src/netconsole/services/ap_identity/` 与 AP Identity Repository/Index；
- `src/netconsole/services/job_center/task_application_service.py`、Job Runtime、`src/netconsole/background_worker.py`；
- 共享 Export Process/Artifact 协调器；
- `src/netconsole/core/paths.py`、DataRoot 与数据库升级/迁移；
- `apps/desktop_electron/src/main/`、`preload/`、`shared/` 和 Python Electron Runtime；
- `.github/workflows/` 与 `scripts/build/`。

任何 L3/L4 任务在编码前、范围扩大后和交付前都必须输出并更新：

1. 风险等级；
2. 影响消费者；
3. 兼容性风险；
4. 回归范围与实际结果；
5. 是否存在并行修改。无法确认其他 worktree/线程状态时写 `UNKNOWN`，不得写成“无”。

## 开发中

- 先理解现有代码，再动手。
- 优先复用现有模块，不新增重复抽象。
- 使用 `apply_patch` 做手工编辑。
- 不回退用户或其他任务留下的改动。
- 不使用破坏性 git 命令。
- 不把局点、线路、车号、AP、MAC、IP 写死。
- 不为旧数据加临时兼容补丁。

## UI 表格开发规则

新增或修改表格时，必须遵守 [Vue 表格与高密度数据规范](ui_table_guidelines.md)。

尤其注意：

- 勾选列使用 `el-table-column type="selection"` 和稳定业务 ID。
- 表格列宽使用明确宽度或 `min-width`，允许用户手工调整。
- 不允许为了塞进窗口而强行压缩核心字段。
- 超宽表格必须使用横向滚动条。

## 修改范围控制

| 任务类型 | 默认修改范围 |
| --- | --- |
| UI 调整 | 对应页面、必要共享样式、对应测试 |
| 导出报表 | 导出进程、导出 job、进度协议、格式 helper、导出测试 |
| 采集解析 | 后台 worker/进程、服务/解析器、命令白名单、解析测试 |
| 轨道交通规则 | 轨道交通服务、页面调度、业务测试 |
| 打包 | `scripts/build/`、构建脚本、打包测试、发布文档 |
| 文档整理 | `README.md`、`docs/`，不改业务代码 |

L3/L4 修改必须先查机器可读 Consumer Matrix，不以“当前模块测试通过”替代消费者回归。当前 CI 对 Python、Renderer 和 Electron 运行的完整套件是矩阵最低要求的上位覆盖；矩阵仍用于说明为什么必须运行这些套件，以及后续测试压缩时保留哪些长期契约。

## Worktree 生命周期

- 每个 worktree 只归属一个任务/线程；不得在主 checkout 或其他任务 worktree 直接编辑。
- 普通功能分支尽量当天完成，原则上不超过 1～2 天。超过两天、基线已明显前移或开始出现大量非本任务冲突时，从最新 `main` 新建 worktree/分支，只迁移本任务提交。
- 不为“保持最新”反复把 `main` merge 到业务分支。同步产生不属于本任务的冲突时停止解决并交给集成负责人判断。
- L3/L4 开始前检查目标高风险文件是否被其他活跃 worktree/线程修改；不能确认时报告 `UNKNOWN` 并避免并行编辑。
- 分支验证只证明该分支组合；合并后以 `main` 最终提交重新运行 Consumer Matrix。`main` 复验失败时基线为红，不得继续发布或叠加新的共享层重构。

## 必须避免

- 只改 UI 表象但破坏底层能力。
- 在 Renderer 直接执行网络连接、设备采集、大查询、大解析、大导出、压缩、图表生成或长时间循环。
- 导出按钮直接调用 `Workbook.save()`、`df.to_excel()`、`matplotlib.savefig()` 等重型导出逻辑。
- 切换主题时重建页面或清空日志。
- 模块切换时重新初始化所有子页。
- 让旧异步请求覆盖当前页面状态。
- 在导出中依赖 WPS/Excel 客户端筛选。
- 在测试里写死用户本机路径或真实现场数据。

## 状态和任务

- 后台采集、检测、导出和进程状态不应因页面切换丢失。
- 服务端/客户端、AC/Rail、TC1/TC2 等相邻状态要分离，不能互相覆盖。
- 主题切换、懒加载、页面刷新不能停止正在运行的任务。

## 验证输出

完成后说明：

1. 修改文件列表。
2. 每个需求对应实现点。
3. 是否涉及数据库结构。
4. 是否涉及导入导出模板。
5. 是否涉及耗时任务，采用 Job Center 还是 Export Process。
6. 是否遵守 Renderer 只做 UI、数据库连接不跨线程/进程共享。
7. 验证命令或手动验证步骤。
8. 已知限制。
9. L3/L4 的影响消费者、兼容性风险、回归范围和并行修改状态。

文档任务还要说明是否修改业务代码；正常应为“否”。
