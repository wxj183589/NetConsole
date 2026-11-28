# Phase 5 真实线路数据

复用 Phase 4 的 HZL10 隔离回放根，采集关闭且历史只读。Electron 列出 2026-11-20 至 2026-11-25 共 6 个已结束 Run。切换后旧结果清空，六次查询均按独立 Run ID 返回 25 条和下一页游标。HZL9 的一个 READY Run 本轮经只读 SQL 核对。HZL10 专用 Quick Ping 仍为 NOT AVAILABLE。

从 HZL10 的 11 月 21 日回放执行 CSV 导出。Windows 原生对话框保存中文文件名，文件 3,842,208 字节，含 5,778 条时间轴记录。取消保留原 SHA-256 `B92CF7FA662A8B18B30BC4508C3FED41B067FA44A6289F31FF0737ED2A72FFFD`。确认覆盖后文件重新写入，最终 SHA-256 `6E5BCCE9BFBA2B9014D192387E83F48ED5C3C6E124421AF55091B9D67C7A0DFF`。验收文件只存于本机 Workspace 报告目录。

[历史对照](UI_UX_PHASE4_REAL_DATA_ACCEPTANCE.md) · [截图及脚本](UI_UX_PHASE5_SCREENSHOT_INDEX.md)
