# Desktop WebHost 与历史 Qt 宿主

## 当前状态

唯一 FastAPI Core Runtime 由 Electron Main 启动的受管 Backend 创建，并交给 Electron 的唯一 Vue Renderer。源码态本机浏览器和无 Shell Server 只保留开发诊断/API 联调用途，不是独立产品入口。Qt Shell、`src/netconsole/ui/` 与 `apps/desktop/` 下的受跟踪源码、Qt probe 和旧 `--web-shell` 启动路径均已删除，历史行为只通过 Git 与 Electron-only 迁移归档追踪。

## 运行结构

```text
NetConsole Desktop Runtime
        |
        v
Core Runtime / FastAPI / Uvicorn
        |
        +-- Electron / 唯一 Vue Renderer（正式桌面产品）
        |
        +-- Browser / Server（仅源码开发诊断）
```

本地服务只绑定 `127.0.0.1`。桌面 WebHost 每次进程启动生成新的临时会话令牌；令牌通过 `POST /__desktop_session` 建立 HttpOnly、SameSite Cookie，不进入 URL。HTTP 和 WebSocket 在会话建立前均拒绝访问。

开发诊断用外部浏览器兼容入口会在 `runtime/cache/` 创建临时自提交页面，令牌只存在于 POST 表单正文，文件在 60 秒后或主程序退出时删除。该令牌只保护本地 WebHost，不替代 Agent 的 `X-Agent-Token`，也不会写入任务、数据库或业务日志；该入口不进入客户发布导航或人工对等验收。

## 生命周期

- Electron Main 启动一次受管 Backend，后端就绪后再加载 Vue；
- 关闭子任务窗口只隐藏窗口，不停止后台任务；退出 Electron 时由统一屏障停止 Backend；
- Python 诊断 Launcher 退出时统一停止 Uvicorn 和 FastAPI lifespan；本机浏览器标签关闭不等于停止诊断 Runtime；
- Electron 启动失败时报告明确错误；不把系统浏览器或 Qt 静默当成正式产品回退；
- 源码开发态 `--mode web/server` 通用导入链不加载 PySide6；`server` 不主动打开浏览器；
- 旧 `--mode auto/qt`、Qt probe、`--web-shell` 与 `netconsole.app.run()` 均不存在活动入口。

## 构建

`scripts/build/build_release.py` 在 Python 打包前执行 `apps/web` 的 `pnpm build`，并把忽略提交的 `apps/web/dist` 作为 `netconsole/assets/web` 内部资源打入 PyInstaller/Nuitka 发布包。构建机需先完成：

```powershell
cd apps/web
pnpm install --frozen-lockfile
cd ../..
```

缺少 pnpm、`node_modules`、`dist/index.html` 或 `dist/web-build-meta.json` 时，发布构建明确失败，不生成缺少完整 Web 页面的桌面包。发布链每次都重新执行 Vue build，不再因旧 `index.html` 已存在而跳过；构建后同时校验应用版本、提交、build id、构建时间和导航 schema 版本。

## 前端资源身份

- 源码模式只加载当前项目的 `apps/web/dist`，不再按文件存在性优先选择虚拟环境、旧安装目录或 `src/netconsole/assets/web`；
- PyInstaller/Nuitka 冻结模式只加载包内 `netconsole/assets/web`，不跨模式回退到源码目录；
- Vite 生成 `web-build-meta.json`，包含 `app_version`、`git_commit`、`build_time`、`navigation_schema_version` 和 `build_id`；
- `GET /api/health` 返回后端 `build_id`；新版 Vue 在前后端 build id 不一致时显示固定顶部警告；旧产物缺少 metadata 时 FastAPI 静态入口仍会注入相同警告；
- Desktop WebHost 启动日志记录 `frontend_root`、`index`、`frontend_build_id`、`backend_build_id` 和 `frontend_source_type`，不记录短期会话令牌；
- 所选模式缺少 `index.html` 时只显示资源不可用页，不静默加载另一运行模式的文件。

WebHost 默认窗口为约 `1360×860`，最小尺寸为 `1024×680`。Vue 导航在低于约 `1100px` 时折叠，低于约 `850px` 时切换为抽屉；折叠状态和展开分组保存在当前会话的 `sessionStorage`。

## 历史 Qt WebHost 阶段边界

以下清单记录 Qt WebHost 迁移阶段的能力快照，用于追踪旧实现，不代表 v1.3.9 当前 Electron 页面状态。当前模块能力以对等矩阵、Feature Registry、代码和测试为准。

- 本阶段已删除 Qt 启动壳，但旧 Qt 页面内部的 Task/Application Service 和业务逻辑仍需按迁移矩阵审计；不能据此声称全仓零 Qt。Electron Bridge 见 [Electron Desktop](ELECTRON_DESKTOP.md)；

- 当前 Web 页面包含 Dashboard、只读任务中心、Agent 管理、AC FIT-AP 资源、AC Mesh-Link 在线监控、Traffic、只读 Online MR 实时展示、轨道交通基础资料、在线列车通信检测、Mesh 原始日志分析和轨道交通无线综合看板；任务中心通过 GET-only `/api/job-center` 查询任务快照、结构化事件和 Online MR 映射，不提供 stop、force-stop、delete 或 retry；Mesh-Link 页面可跳转查看其刷新任务；
- 任务列表按运行状态动态使用 2 秒或 5 秒轮询，连续失败后降为 10 秒；详情每 2 秒刷新，日志展开后每秒读取最后 300 条，页面隐藏或关闭后停止全部轮询；
- Job Center 查询以 SQLite `mode=ro` 和 `query_only` 打开当前局点 `tasks.db`，不初始化 schema、不修复状态，也不返回任务结果中的完整业务 payload；
- Online MR 在显式启用时提供 LOCAL start/normal stop/force-stop/recover；正式 Electron Runtime 显式启用，其他宿主未传参时仍由 `ONLINE_MR_WEB_CONTROL_ENABLED` 控制。在 `ONLINE_MR_AGENT_EXECUTOR_ENABLED=1` 时提供独立 AGENT start/status/normal stop；两类控制路由都要求 Desktop 模式、严格 `127.0.0.1` 与已认证短期 Cookie。WebHost 没有 Agent 强停、任意命令或任意 URL API；
- Online MR Web 仅读取当前局点的 Session metadata、Task/Mapping、`view/*.json` 和 raw 白名单；页面隐藏或关闭后停止轮询；
- AC 管理通过 GET-only `/api/ac-management` 和 SQLite `mode=ro + query_only` 展示现有 AC/FIT-AP、Radio 1/2、LLDP、光衰及配置快照；不连接设备、不采集、不下发命令，配置文件仅通过受控 snapshot ID 分块读取；
- AC Mesh-Link 查询仍使用 GET-only 接口并按 30 秒 fresh/5 分钟 stale 边界保守展示 MR 状态；唯一 `POST /api/ac-management/mesh-links/refresh` 只接受 AC 标识和 switch-history 布尔开关，通过 Task Center Worker 执行固定只读命令。WebHost 不持有设备凭据、不接受命令文本；旧采集没有 raw 时明确显示不可用；
- 轨道交通基础资料通过 SQLite `mode=ro + query_only` 展示站点/区间派生视图、AP 点位、列车/MR、关联状态和按实体分组的质量问题；导入预览不保存上传原文件。5C-6B 的 apply/审计/rollback API 受 `web.rail_transit_base_data_write`、环境开关、局点范围、预览有效期和数据库哈希共同保护，默认配置不显示应用按钮，真实局点写入仍未授权；
- 在线列车通信检测按列车分开显示 MR-CT/MR-TC，并聚合 Mesh-Link、Online MR、fping/iPerf、Task 和采集包；聚合与 raw tail 保持只读，MR 详情的独立控制区只向 `OnlineMrApplicationService` 提交严格业务 DTO。页面隐藏或卸载只停止轮询，不停止采集；
- Mesh 原始日志分析以 `mode=ro + query_only` 读取既有单来源分析数据库，后端分页链路、降采样 RSSI/空口、复用正式短时/乒乓规则并列出现有报告；不创建 Task、不调用 parser 写入模式、不生成或删除报告，文件访问不接受路径参数；
- 轨道交通无线综合看板通过既有 Query Service 聚合基础设施、列车通信、任务、Agent 缓存和 Mesh 分析摘要；全部接口为 GET-only，告警不增加业务阈值，页面只跳转到已有详情入口；
- WebHost 只在独立 AGENT 页签开放已登记 Profile 的远程 MR start/status/normal stop，不开放远端包删除、强停、任意命令、任意 URL 或 Agent 配置修改；Application Service 的单 Agent 执行闭环见 [Online MR Agent 远程执行器](ONLINE_MR_AGENT_EXECUTOR.md)；
- Agent Web 当前生产认证仍是可选 `X-Agent-Token`。示例配置虽保留 `web_username/web_password` 字段，但尚未实现用户名密码登录流程，不能把 `admin/admin` 描述为已生效认证；
- SNMP Center、通用 MIB/OID 平台和无线勘测已删除；网络工具无线扫描独立保留。
- Web 导航、实际路由和未完成规划由 `apps/web/src/navigation/registry.ts` 统一描述；未实现项保持隐藏且不注册占位业务路由。完整状态见 [Qt/Web 功能对等矩阵](WEB_QT_PARITY_MATRIX.md)。
- Electron 已实现文件/目录/另存为、会话内授权路径和受管后端下载，Browser 继续使用普通下载。按业务 ID 打开的 `openArtifact`、终端与通知按实际 Feature 状态验收；所有能力必须遵守 [Desktop Native Bridge 契约](DESKTOP_NATIVE_BRIDGE.md)。
- Electron 先拒绝新下载并取消、等待在途写入，再通过 `shutdown_ack -> exit` 控制握手停止受管 Python，所有清理完成后才退出。Qt WebHost 只作为 Git 历史和待删除源码的迁移参考。
