# NetConsole Phase2 性能专项最终报告

日期：2026-08-26

基线：`main` `e6a05df898c2b6015dfc97408196b1902cae87e0`；本报告对应的 Phase2 优化代码已通过定向验证，随后单独形成优化提交。

## 本轮完成

1. Trackside snapshot：设备接口、光模块、LLDP 从逐设备读取收敛为批量读取，并保留异常降级；重复站点扩展点读取消除。
2. MESH query：按图表请求分辨率收紧默认 source series materialization，避免默认响应先构造随后被丢弃的宽 series。
3. Site Switch：复核并沿用已合入 main 的 `4a13213e` warm handoff，没有重复实现 backend lifecycle。
4. FIT-AP：复核已有批量页加载，无需再次改动。

## 自动化验证

- Trackside/设备事实相关：109 passed。
- MESH query service：100 passed。
- Ruff：通过。
- changed Python files compileall：通过。
- `git diff --check`：通过。

## 性能结果摘要

| 热点 | 历史基线 | 当前证据 | 状态 |
| --- | ---: | ---: | --- |
| Site Switch | 8.5–14.4s backend restart | warm handoff metadata 历史 DEV 362–453ms；本轮启动无 restart | PARTIAL，待最终 GUI 交替复验 |
| FIT-AP | 静态审计疑似 N+1 | 真实页 164–316ms，批量明细生效 | PASS |
| Trackside snapshot | 72.4s | 直接快照读取杭州 1.31s、宁波12 8.73s | PARTIAL，历史解码仍是宁波热点 |
| MESH table | 11.59s / heap 3.22GB | link page 0.65s | PASS，GUI 滚动仍待补 trace |
| MESH chart/query | 约 17.06s profiling | 2.02s；source A/B 16.89s -> 7.50s | PASS |

## 明确未做

- 未修改生产数据、数据库 schema、AP Identity、LLDP 规则、Task/HistoryStore 模型。
- 未加入新缓存、全局表格重写或跨热点并行优化。
- 未把真实数据、原始 trace、IP、设备标识或生成文件提交到仓库。

## 下一任务建议

只新建一个独立任务，优先处理 Trackside snapshot 的 HistoryStore 历史分片读取、压缩解码和可证明的批量/边界策略；先完成该任务的 DEV 验收，再进入 MESH renderer 的 GUI long-task/滚动 trace，最后再评估 MESH full scan。Site Switch 另补最终 commit 上的两局点 GUI 交替验收。
