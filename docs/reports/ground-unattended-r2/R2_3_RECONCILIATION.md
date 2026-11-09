# R2.3 Syslog / AC 对账报告

日期：2026-11-10。结论：投影优先级 **PARTIAL**，完整跨源验收未完成。

## 当前读取优先级

| 条件 | API/UI 当前位置 | 说明 |
| --- | --- | --- |
| 有精确 Syslog position projection | 使用 Syslog current/previous AP | 展示 `SYSLOG`、质量、状态、新鲜度和时间字段 |
| Syslog 投影过期 | 仍可展示最后已知位置，但标记 `STALE` | 不显示为实时；不会由过期值伪造新事件 |
| Syslog 未解析/未识别 | 保留已有位置或返回未知 | 不猜测 AP，不清空原有精确位置 |
| 没有精确 Syslog 位置 | 保留既有 AC/Wmesh 辅助字段 | 只能作为 fallback，不能反写 Syslog 位置历史 |

`GroundUnattendedApplicationService` 在 endpoint enrichment 中读取位置投影，并在 train DTO 中优先输出精确 Syslog 当前位置；AC 延迟快照不会在该读取投影阶段无条件覆盖较新的 Syslog 位置。UI 同时显示 freshness/source/status，避免把旧位置标为实时。

## 未完成

尚未执行“先写 Syslog A→B、再注入延迟 AC A”以及反向冲突、时间相同、身份 revision 变化的端到端测试。因此本报告只确认代码边界，不宣称完整 AC/Syslog 事实对账通过。
