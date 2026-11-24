# Phase 3 工程关系验收

当前交付状态：验收执行中。最终 Full Gate 结果和提交身份以 Workspace 报告为准，不能把 Phase 2.5 历史 PASS 当作本轮结果。

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
