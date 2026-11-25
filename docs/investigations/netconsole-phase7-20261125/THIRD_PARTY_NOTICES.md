# Phase 7 第三方组件与离线分发说明

本清单从现有机器可读 Notice 生成，版本、用途和许可证以 `src/netconsole/assets/open_source_notices.json` 为事实源。对应文档副本为 `docs/open_source_notices.json`，本轮已验证两者逐字节相同。完整声明复用 `src/netconsole/assets/THIRD_PARTY_COMPONENTS.md`、`src/netconsole/assets/licenses/` 和版本化网络工具目录中的许可证及来源材料。

## 已登记组件

| 组件 | 版本 | 用途 | 许可证 |
| --- | --- | --- | --- |
| Python | 3.13.9 | Python Backend 运行时 | PSF License |
| fastapi | 0.139.2 | FastAPI Backend HTTP API | MIT |
| python-multipart | 0.0.32 | multipart 表单解析 | Apache-2.0 |
| pydantic | 2.13.4 | DTO 与配置校验 | MIT |
| uvicorn | 0.51.0 | ASGI Backend 服务器 | BSD-3-Clause |
| websockets | 16.0 | ASGI WebSocket 协议实现 | BSD-3-Clause |
| httpx | 0.28.1 | Backend HTTP 客户端 | BSD-3-Clause |
| netmiko | 4.7.0 | 网络设备 SSH/Telnet 连接与命令采集 | MIT |
| paramiko | 4.0.0 | SFTP、SSH Tunnel 与 SSH 错误映射 | LGPL-2.1 |
| cryptography | 49.0.0 | 受管 HTTPS/FTPS 自签服务证书 | Apache-2.0 OR BSD-3-Clause |
| pyftpdlib | 2.2.0 | 受管本地 FTP 服务 | MIT |
| pyOpenSSL | 26.4.0 | pyftpdlib FTPS 服务端 TLS 支持 | Apache-2.0 |
| pyasynchat | 1.0.5 | 本地 FTP 运行时兼容依赖 | PSF-2.0 |
| pyasyncore | 1.0.5 | 本地 FTP 运行时兼容依赖 | PSF-2.0 |
| openpyxl | 3.1.5 | Excel 文件导入与导出 | MIT |
| XlsxWriter | 3.2.9 | 大数据量 Excel 流式导出 | BSD-2-Clause |
| matplotlib | 3.11.0 | 分析图表绘制 | Matplotlib-1.3-license AND bundled third-party notices |
| numpy | 2.5.1 | 数值计算和图表数据处理 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| tzdata | 2026.3 | Windows 冻结 Backend 的完整 IANA 时区数据库 | Apache-2.0 |
| PyInstaller | 6.21.0 | 冻结 Backend 的 bootloader 与运行时 hooks | (GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0 |
| pyinstaller-hooks-contrib | 2026.6 | 随 Backend 归档的第三方运行时 hooks | Apache-2.0 |
| Electron | 43.1.1 | Windows 桌面外壳 | MIT |
| Chromium | 150.0.7871.114 | Electron 内嵌浏览器运行时 | BSD-3-Clause |
| Node.js | 24.18.0 | Electron Main/Preload JavaScript 运行时 | MIT |
| fping | 5.5 | Windows x64 Cygwin 高频 Ping 工具 | BSD-like; bundled COPYING |
| Cygwin Runtime (fping bundle) | 3.6.9 | fping.exe 的 Windows POSIX 运行时 | LGPL-3.0-or-later WITH Cygwin-exception-3.0 |
| iPerf3 Windows x64 Cygwin dynamic-auth | 3.21 | Windows x64 TCP/UDP 流量测试与可选 authentication；ar51an Apache-2.0 适用于构建分发仓库 | BSD-3-Clause and bundled permissive notices |
| cJSON (embedded in iPerf3) | 1.7.15 | iPerf3 JSON 输出 | MIT |
| Cygwin Runtime (iPerf3 bundle) | 3.6.7 | iPerf3 Windows bundle 的 POSIX 运行时 | LGPL-3.0-or-later WITH Cygwin-exception-3.0 |
| OpenSSL Runtime (iPerf3 bundle) | 3.0.19 | iPerf3 authentication 加密运行时 | Apache-2.0 |
| zlib Runtime (iPerf3 bundle) | 1.3.2 | OpenSSL/iPerf3 压缩运行时 | Zlib |

## 离线与来源约束

运行时工具从仓库白名单复制，依赖锁定在 constraints.txt 与前端 pnpm-lock.yaml。正式包不在客户机联网安装 Python、Node 或网络服务依赖。构建机的锁定依赖安装与客户机运行时分别验证。

TFTP、HTTP、HTTPS 和 Syslog 通过现有 Python 服务进程管理。FTP/FTPS 使用 pyftpdlib、pyOpenSSL 与 cryptography。系统 OpenSSH、Telnet、NFS、VNC 属于主机已有能力或明确缺失依赖，未作为未知第三方二进制加入本轮包。

Electron/Chromium/Node 随当前锁定 Electron 分发，固定网络工具的二进制 SHA-256、来源和许可证继续由现有 Notice、provenance 和包级合规检查验证。IPOP 用户外部工具保持现有自备边界。

正式构建生成 CycloneDX 1.5 SBOM，并用独立 cyclonedx-bom 交叉核对 Python 完整运行依赖闭包。最终 SBOM 路径与包级检查结果记录在安装包验收报告。

## 分发责任

Cygwin 运行时的对应源码或有效书面方案按工具目录 CORRESPONDING_SOURCE.md 随正式分发履行。构建通过与最终对外分发材料完整性分别记录。

机器可读 Notice 验证为 PASS，组件数为 31。最终冻结制品的版本、哈希、许可证清单和 SBOM 仍由正式构建 Gate 复核。
