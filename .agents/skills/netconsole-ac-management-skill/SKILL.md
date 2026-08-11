---
name: netconsole-ac-management-skill
description: "NetConsole AC 管理、FIT-AP 资源、受控固化新 AP、开启 AP 远程登录、动作计划/确认/审计、OmniPeek .nam 名称表或 AC 作用域匹配任务时使用。普通设备管理、无 AC 作用域的 AP Identity 或轨旁光衰分析不使用本 Skill。"
---

# 目标

维护 AC/FIT-AP 查询、强类型危险动作和 OmniPeek 名称表闭环，保证前端不提供任意命令、确认凭据不泄露、数据不跨 AC 混合。

# 输入与路径

确认目标局点、AC ID、动作语义、AP 勾选范围、预期 Artifact 和复现步骤。先读 `docs/AC_MANAGEMENT.md`、`apps/desktop_renderer/src/views/ac-management/README.md`、`src/netconsole/application/ac/`、`src/netconsole/services/ac/`、AC Router/DTO/Vue、`tests/test_ac_management_web_api.py` 与相关 OmniPeek/动作测试。

# 工作流

1. 从代码、测试、当前 diff 和 Command Profile 核对动作 ID、命令生成方、计划摘要、确认、执行、审计和任务终态。
2. 固化与远程登录只允许后端 `ACTION_DEFINITIONS` 强类型动作；Vue 只提交业务 ID，不提交命令文本。
3. 页面只应保存/显示 `plan_id`；`confirm_token` 不渲染、不记录、不持久化。审计 DTO 与 client 是否仍让 Renderer 接收 Token；存在时报告为待修复边界，不能只用“不显示”判定安全完成。
4. 同一 AC 写动作使用 AC 级 resource key 互斥；`actionTask` 与资源刷新状态分离，不锁死其他 AC。
5. OmniPeek 勾选时只导出勾选 AP，未勾选时导出当前 AC 全部 FIT-AP；扩展信息必须以当前 AC 资源为集合边界，排除设备管理车载 MR。
6. 复用共享 MAC 标准化、R2 推导和名称冲突逻辑；预览进 Job，`.nam` 进 Export Process。

# 安全与禁止

不得增加任意命令、SNMP SET、前端命令模板、Token 日志、跨 AC AP fallback 或真实凭据/地址。不得为通过测试放宽版本 Profile、确认有效期、资源互斥或审计。

# 验收与命令

优先运行 `.venv/Scripts/python.exe -m pytest -q tests/test_ac_management_web_api.py tests/test_ac_action*.py tests/test_omnipeek*.py` 中存在且受影响的文件，并在 `apps/desktop_renderer` 运行 AC 页面定向 Vitest；最后执行 `git diff --check`。真实 AC、OmniPeek 导入和 Electron 保存未执行时明确标为待验收。

# 常见失败与报告

常见失败：Token 暴露、动作与刷新共用 loading、同 AC 并发写、扩展行混入其他 AC、车载 MR 进入名称表、前端生成 XML/命令。报告修改文件、动作/导出范围、安全边界、命令是否变化、资源 key、数据/导出影响、测试命令和现场限制；同步 `docs/AC_MANAGEMENT.md`、README、Feature/CHANGELOG。
