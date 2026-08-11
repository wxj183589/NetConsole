---
name: netconsole-config-collection-skill
description: "NetConsole 配置采集中心、running/saved 快照、两文件或跨设备对比、display version 内容裁剪、双栏 Diff、快照删除/恢复或配置 Artifact 导出任务时使用。AC 配置快照、普通文本 diff 或设备文件下载不使用本 Skill。"
---

# 目标

维护配置采集、快照选择与可追溯差异链路，保证两条勾选真正成为对比输入，文件与路径安全由后端控制。

# 输入与路径

确认设备/快照 ID、类型、左右来源、文件边界和复现步骤。先读 `docs/CONFIG_COLLECTION.md`、`apps/desktop_renderer/src/views/config-collection/`、Config Router/DTO、`config_collection_web_service.py`、`config_lifecycle_service.py`、config Job handlers 与对应 Python/Vue 测试。

# 工作流

1. 勾选恰好两条快照时用作左右对比；一条禁用，超过两条只允许批量 ZIP/删除。手工左右选择可跨设备保留。
2. 切换设备、快照类型或刷新时清空不可见勾选，不让旧表状态覆盖手工选择。
3. 校验左右 ID 不同、属于当前局点且文件引用受 PathResolver 管理；前端不传本机路径、命令或凭据。
4. 先核对 `extract_h3c_configuration_body()` 的实际边界。当前是首个独立 `#` 到最后 `return`；若需求改为 `display version` 到末尾 `#`，必须修改 Python 与 fixture，Vue 不猜测。空文件、相同文件、不同设备和缺边界均有明确结果。
5. 对比进 Job，ZIP/差异文件进 Export Process；双栏视图只消费结构化 diff 行，左侧树与结果区可独立滚动。
6. 删除使用确认、隔离和数据库失败回滚；任务支持进度、取消、恢复和安全 Artifact。

# 验收与命令

运行 `.venv/Scripts/python.exe -m pytest -q tests/test_config_collection_web_api.py` 及直接受影响的配置服务测试，在 `apps/desktop_renderer` 运行 `ConfigCollectionView.test.ts` 与 `configDiff.test.ts`；最后执行 `git diff --check`。

# 常见失败与报告

常见失败：勾选只用于批量动作未进入对比、设备切换复用旧勾选、同文件自比较、空文件被当失败、把目标裁剪规则写成当前事实、Renderer 读取路径、删除失败不恢复。报告选择语义、裁剪/差异规则、左树收起是否真实存在、修改文件、Job/Export/磁盘影响、测试和真实设备限制；同步 `docs/CONFIG_COLLECTION.md`、页面 README、Feature、REFACTOR_MAP 与 CHANGELOG。
