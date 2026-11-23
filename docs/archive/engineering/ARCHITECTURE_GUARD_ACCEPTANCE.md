# Architecture Guard Acceptance

日期：2026-11-23

## 目标

本轮只处理 `normalizedStatus`、`classifyPingStatus` 和 `naturalSecondLossBuckets` 三项 Renderer 业务逻辑债务；未修改 `normalizeMac` 的既有 `DISPLAY_ONLY` 分类，也未新增豁免。

## 结果

执行：

```powershell
python scripts/architecture/check_ui_business_logic.py
```

结果：`[PASS] ui-business-logic: 0 finding(s), 0 waived`

三个目标符号已从 Renderer 运行路径删除，Backend 实现在 `src/netconsole/services/ground_unattended/ping_business.py`，调用接入 `GroundUnattendedApplicationService`。`config/architecture/ui_business_logic.yaml` 仅移除三条真实债务记录，并登记了分页桶的展示合并函数。

`ARCHITECTURE_GUARD=PASS`。这不等同于 v1.5.18 正式发布通过；Root Layout 中的历史 v1.5.17 文件和其他 Release Gate 仍按既有门禁处理。
