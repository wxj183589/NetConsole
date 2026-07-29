# Web Pinia Stores

本目录维护跨组件共享的前端状态，按业务域保存请求状态、筛选条件、任务事件和轻量缓存。Store 不应直接访问设备、SQLite 或启动进程。

主要入口为各域 `*.ts` 与测试；API 调用通过 `src/api`。修改状态字段、清理时机或错误状态时运行对应 Store 测试。

主题不进入 Pinia：系统设置 API 是主题与强调色的唯一持久化来源，`settings/appearance.ts` 和 `theme/theme.ts` 负责启动解析与运行期同步，Store 不建立 `localStorage` 或第二份主题状态。

`workspace.ts` 是当前工作区标签的事实源；标签、顺序、活动路由和缓存键只保存在当前进程内存，通过 Electron Bridge 传递的快照也只服务当前进程内 Renderer 重载与局点切换回滚。遗留 `openPageTabs.ts` 同样保持纯内存并固定从 Dashboard 初始化，不读取或写入 Web Storage。
