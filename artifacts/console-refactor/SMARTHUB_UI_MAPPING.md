# SmartHub UI 映射

## 证据分级

| SmartHub 线索 | 证据级别 | Console R2 处理 |
| --- | --- | --- |
| 左侧资源导航 + 中部工作区 + 工具区域 | 研究文档与重构 UI 支持 | IMPLEMENTED：设备/会话双视图、中央终端工作区 |
| 设备树、搜索、状态、分组 | Device Manager 文档与已还原页面支持 | IMPLEMENTED：复用旧版 Device Service，不建立第二数据源 |
| 多标签与终端样式 | Console reconstruction 文档支持 | IMPLEMENTED：独立 xterm 实例，关闭标签不终止后端会话 |
| 分屏 | 研究文档支持，缺少同状态原版截图 | IMPLEMENTED，视觉标记 EVIDENCE_GAP |
| SFTP/FTP 组件 | 组件/研究文档支持 | IMPLEMENTED：独立 Paramiko SFTP subsystem、浏览和传输队列，不复用终端 Shell Channel |
| AI 工具区 | SmartHub 产品线索 | 明确移除；Console R2 不含 AI UI 或依赖 |
| 完整真实终端行为 | 无可靠 SmartHub 运行证据 | EVIDENCE_GAP：不宣称 SmartHub 原版已验证真实 SSH/Telnet |

没有找到可与 Console R2 所有状态一一对应的 SmartHub 原版控制台截图。因此布局采用已证实的信息结构，终端、分屏、SFTP 和历史细节以旧版现有设计系统与 SecureCRT 类交互为准，不伪造像素级还原结论。
