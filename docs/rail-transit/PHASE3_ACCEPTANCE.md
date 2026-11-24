# Phase 3 工程关系验收

当前交付状态：PARTIAL。工程关系实施、定向自动化与合成局点 Electron 验收已执行；完整 Full Gate 未完成。用户在执行期间更新规范为“尽量使用定向测试，不要使用全量测试”，因此停止全量进程，保留完整日志，不继续重跑，不将 Phase 2.5 历史 PASS 或本轮子集通过当作 Phase 3 Full Gate PASS。

实现验证提交：`76eb295ac44eb67f685613e35885211118360573`。后续收口仅更新验收文档，产品最终提交以 Git HEAD/DevStatus 为准。Full Gate 比较基线仍记录用户原指定 `907183a4`，没有改用较近基线缩减要求。

## 实施内容

- 设备主要安装节点与多区间服务范围独立，工程角色/位置可维护，保留原单站点字段。
- AC 多站点原子批量关联、修改、解除、历史及独立 FIT-AP Current 概览。
- 列车 CT/CW 正式关联、解除、更换；旧资产和历史会话保留，Ground 当前缓存按 revision 更新。
- 车站与建设项目多对多关联，项目创建/更名及站点列表。
- 统一服务端权限、事务、幂等、revision 冲突、预览、历史时点与删除保护。
- 现有三栏工作台接入，预览/确认、保存状态、失败草稿、显式刷新版本和离开保护。

## 可追溯证据

实现与边界见 [写入契约](RELATIONSHIP_WRITE_CONTRACT.md)、[历史语义](RELATIONSHIP_HISTORY.md) 和 [能力审计](PHASE3_RELATIONSHIP_AUDIT.md)。

测试证据目录：`D:\study\NetConsole-Workspace\reports\tests\rail-relationship-phase3`。包含 Full Gate 日志/摘要、关系专项、跨模块回归、迁移报告、Electron 验收和 screenshots。截图使用实际 Electron + 正式会话 + 合成局点，视口 1920×1080、2560×1440；写入成功使用真实 API，网络失败场景明确为传输故障注入。

未操作 Production 或 Dev Authority，没有真实设备、现场切换、安装包或部署验收。未来 main 合并结果独立验收。关系接口始终不提供资产删除许可；无法确认外部历史证据时失败关闭。未来调度与双时态录入视图不在当前能力中。

PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO

## 已执行与待验收

最终定向回归使用关系、基础设施、设备详情/管理、Ground inventory/heartbeat/quick_ping、基础资料 API、AC/FIT-AP、轨旁快照、Wireless/MESH、Online MR 的实际 consumer 测试文件；结果：419 passed（18 warnings），见 Workspace targeted-consumers.log。main contract smoke 12 passed、Architecture 12/12、文档规则 22 passed、Ruff 和 diff check PASS。Renderer 217 files / 1,582 passed，类型检查与构建通过；关系交互定向 3 files / 14 passed。实际 Electron 36 张截图（18 场景 × 2 视口）。

Full Gate：最后一轮在 Python 34% 时按用户更新规范停止，未取得完整 Python/Electron/Architecture 的该轮最终结果。第一轮失败与第二轮主动中止均单独保留，不拼接为一次 PASS。后续是否执行完整验收由新的明确任务决定。

删除预检采用失败关闭：工程关系当前/历史引用可检查，外部任务、报告、AP Identity、Online MR 等完整删除许可审计仍 NOT_VERIFIED，接口始终拒绝删除。本次未实现通用资产删除授权聚合；不要把它当作“所有删除预检已完成”。

真实设备与现场环境、真实数据库升级、安装包、长时运行和未来 main 合并验证仍 NOT RUN。
