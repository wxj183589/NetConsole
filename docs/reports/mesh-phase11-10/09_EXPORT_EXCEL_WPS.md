# Excel / WPS 导出验收

## MESH 分析报告

真实 Electron 点击“生成分析报告”，使用 Windows 原生保存对话框写入：

D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-10-evidence-001\MESH-phase11-10-report-20261110.xlsx

- task：rail-export-0e74a309303441b596e0a56c41e7582c
- UI：COMPLETED / 100%
- 业务结果：成功
- 任务消息：报告完整性校验完成
- 文件大小：8,425,048 bytes
- SHA256：4CEBF86B00AA1825C4B6BF8EC64AAA0B0F8D10F5BD118F517367B2FEBAA4BCFC
- ZIP：testzip=null
- worksheets：16
- content types / styles / worksheet XML：齐全

18 是完成态 Electron 页面截图，包含任务详情和报告来源记录。

## 链路明细

真实 Electron 点击“导出链路明细”，参数页沿用当前局点默认，使用 Windows
原生保存对话框写入：

D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-10-evidence-001\MESH-phase11-10-link-details-20261110.xlsx

- task：rail-export-ce2a5b646a724293bf2646d980cea4f8
- UI：COMPLETED / 100%
- 阶段：mesh_analysis.export_progress_save
- 业务结果：成功
- 任务消息：报告完整性校验完成
- 处理时间：1m 2s
- 文件大小：21,996,609 bytes
- ZIP：testzip=null
- worksheets：5
- content types / styles：齐全

## WPS

发现并使用真实 WPS：

C:\Users\18358\AppData\Local\Kingsoft\WPS Office\12.1.0.29690\office6\wps.exe

实际打开报告文件，窗口标题为
MESH-phase11-10-report-20261110.xlsx - WPS Office；确认文件可打开后仅关闭
本轮启动的 WPS PID 22324。没有操作用户已有的 WPS 后台进程。

## Excel

本机未找到 Excel 可执行文件，Excel 原生 GUI 标记 NOT_RUN / external blocker。
这不影响 WPS GUI 和 OOXML 结构校验；最终总状态因此为
PASS_WITH_EXTERNAL_BLOCKERS，而不是将 Excel 写成 PASS。
