---
name: netconsole-train-communication-skill
description: "NetConsole 车内通信检测、TC1/TC2 固定拓扑、列车点表、离线列车选择、AC/Mesh-Link 辅助状态、SSH/Ping/跨 TC 检测或 VRRP 字段清理任务时使用。Online MR 实时采集、列车在线页或普通 Traffic 测试不使用本 Skill。"
---

# 目标

维护按有效点表执行的车内通信检测，确保在线状态只作上下文，节点失败可追溯，VRRP 不产生无依据的主备结论。

# 输入与路径

确认局点、列车身份、点表 revision、在线/离线场景和期望 TC1/TC2 结果。先读 `docs/TRAIN_COMMUNICATION_MONITORING.md`、`docs/rail-transit/train-communication/`、相关 Vue/DTO/Router、`train_communication_query_service.py`、`car_network_diagnostic*.py` 和对应测试。

# 工作流

1. 合并基础列车、点表列车和正式 MR，使用 canonical train ID 去重与自然排序。
2. 无快照、过期、单/双端离线或 AC 查询失败仍允许选择并按有效点表启动；在线信息只进入辅助标签和任务上下文。
3. 点表缺失、无效、revision 冲突或没有可执行节点必须阻止启动，返回稳定错误。
4. Worker 按点表继续 MR SSH、节点 Ping 和跨 TC；AC/Mesh-Link 失败不得提前终止，原始异常进入结果和警告。
5. TC1/TC2 表展示各端节点/链路事实；部分节点失败不抹去已完成步骤。
6. VRRP 只展示点表 `vrrp_ip` 静态配置；不得从 Ping、节点或跨 TC 推断 Master/Backup、主端或状态。

# 安全与禁止

前端不提交命令、凭据或路径；不启动 Online MR、持续 fping/iPerf 或轨旁采集；不恢复旧 Qt 页或 VRRP 误导字段。任务继续使用 Job Center JSON 参数、进度、取消、恢复和历史结果。

# 验收与命令

运行 `.venv/Scripts/python.exe -m pytest -q tests/test_car_network_diagnostic.py tests/test_car_network_diagnostic_job.py tests/test_train_communication_query_service.py tests/test_train_communication_web_api.py`，并在 `apps/desktop_renderer` 运行 TrainCommunication/FixedTrainTopology/PointTable 定向 Vitest；最后 `git diff --check`。

# 常见失败与报告

常见失败：把在线当硬门槛、AC 离线即结束任务、点表空仍启动、列车身份重复、VRRP 主端残留、部分失败被写成全部成功。报告可运行/不可运行条件、执行阶段、TC1/TC2/警告语义、VRRP 边界、修改文件、测试与现场限制；同步专题 README、Feature、导航名称和 CHANGELOG。
