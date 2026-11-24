# Phase 4.5 MESH / Online MR

会话详情通过统一工程上下文查询分别返回当前关系与事件时关系，不修改原始会话、日志、解析结果或 Excel。列表仍使用既有轻量查询。

Online MR 使用既有 `device_uuid` / `mr_id` 稳定身份；MESH 仅使用 Profile 中明确的 `linked_device_uuid`。旧数字设备 ID、名称、IP、MAC 不用于猜测资产。缺少稳定身份或事件时间时，历史工程上下文为 `unconfirmed`。

历史查询使用原始会话开始时间或日志首个采样时间，读取 Phase 3 关系有效区间。MR 更换后，旧日志仍保留旧身份，当前关系独立显示。上下文查询失败返回 `unavailable`，原始会话仍可读取。

定向验证：`tests/test_engineering_context.py`、`tests/test_online_mr_query_service.py`、`tests/test_mesh_analysis_query_service.py`。日志位于 Workspace `reports/tests/rail-business-integration-phase4/logs/mesh-mr.log`；最终汇总见 `PHASE4_ACCEPTANCE.md`。
