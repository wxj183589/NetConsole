# Phase 3.7 定向回归

本轮不运行 Full Gate、全量 Python 或全量 Electron。未改 Renderer，因此不新增 Electron 截图，Phase 3 历史 GUI 证据不计入本轮自动化成功。

日志：Workspace reports/tests/rail-asset-safety-phase3-6。安全/关系/设备、跨模块消费者、Architecture、main smoke、Ruff、docs 分开记录。最终执行命令、数量和耗时在同目录 summary.md，不将定向结果表述为 Full Gate PASS。

初轮问题：专项夹具误把 serial_number 当作 devices 列，按事实结构修正为 MAC/UUID（SN 完整链仍未验证）；既有删除成功断言改为明确授权拒绝并保留资产；Router 的 Repository 异常导入违反边界，改由 Service 暴露。设备 CSV 导出出现一次终态先于子进程退出的时序失败，独立复验通过，保留历史失败，不放宽预算或产品断言。

完整历史许可仍 NOT_VERIFIED，整体 PARTIAL。真实设备、生产/开发真实数据、安装包和未来 main 合并复验 NOT RUN。

## 最终执行结果

| 套件 | 结果 | 耗时 |
| --- | --- | --- |
| 删除安全/工程关系/Devices/Infrastructure（6文件） | 162 passed，0 failed，0 skipped | 68.95s |
| Ground/AP/AC/MESH/Wireless/Online MR（13文件） | 323 passed，0 failed，0 skipped | 139.87s |
| Main contract smoke | 12 passed | 17.24s |
| Architecture | 12/12，0 waived | 独立检查 |
| Docs rules | 22 passed | 1.41s |
| Ruff / diff | PASS | 修改范围检查 |

命令采用 python -m pytest 后显式列出上述文件，不使用全库发现。逐项命令/文件与日志详见 Workspace reports/tests/rail-asset-safety-phase3-6/summary.md。安全专项含 19 例。导出时序失败在独立复验及最终整组选定文件均通过，历史日志保留。

已知映射/历史不变量由关系专项和消费者验证；跨库/离线文件完整索引、MAC/SN/旧名称及报告关联完整性仍未证明，不把这一限制写成“没有引用”。不存在本轮已确认且未修复的资产物理删除 Repository 绕过；直接 SQLite、外部维护和其他域的独立删除不属于此保护入口。
