# v1.5.17 缺陷登记

| ID | 等级 | 问题 | 根因 | 处理 | 验证 |
| --- | --- | --- | --- | --- | --- |
| NC-1517-001 | P1（数据安全） | `audit_lifecycle_dev.py` 无参数时隐式读取 `D:\NetConsoleData-dev`，操作者可能在未明确授权时触碰真实开发数据 Authority。 | CLI 将受保护 development 根作为默认 `--data-root`。 | 已修复：要求显式 `--data-root`，并校验路径目录名；保留只读 SQLite 与 development marker 门禁。 | 无参数调用返回 argparse 错误；`py_compile` PASS。 |

## 未确认缺陷

- P0：0
- 其他已确认 P1：0
- P2/P3：发现的维护性观察项记录在安全和 Windows 复审文档，未扩大本次修改范围。

真实设备不可达、GUI、Win10 20H2、8 小时长稳等不是代码缺陷结论，继续沿用上一版本 PARTIAL 验收状态。
