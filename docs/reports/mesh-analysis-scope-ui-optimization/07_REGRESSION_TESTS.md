# 回归测试

定向 Python：Mesh 统计、AP 位置、Mesh Web/API/Query、导出身份共 `178 passed`；本轮 Excel 原始字段一致性与旧导出回归 `49 passed`。定向 Renderer：Tooltip/业务摘要/挂载 `18 passed`，`vue-tsc -b` 通过；既有 Phase 9 图表/页面集成保持通过。Playwright 合成视口：3/3（1920x1080、1920x1080@125%、2560x1440），范围按钮请求参数和无横向溢出通过。

完整 Full Gate 首轮因缺少新增 TitleComponent mock 和一项快照期望失败；修复后按要求重新完整运行并通过：Python `5565 passed, 2 skipped`；Renderer 测试、`vue-tsc -b`、Vite build；Electron `306 passed`、类型和构建；架构 `12/12`；主线 smoke、Ruff、文档路径和 diff 全通过。门禁日志中有既有未启动 `127.0.0.1:3000` 连接拒绝输出，但不影响最终 PASS。

未执行：用户原始 ZIP 文件级审计、真实 Excel/WPS GUI、Windows 原生 125% DPI、真实设备/现场数据和长稳；本轮未重复完整 Full Gate。

状态：`RAW_MESH_FIELD_PRESERVATION_STATUS=PASS`、`TOOLTIP_REGRESSION_STATUS=PASS`；外部验收保持 `PARTIAL`，既有 Full Gate 结果保留但本轮不重新宣称全量复验。
