# 通用纯函数工具

本目录收纳跨域复用的排序、接口/MAC/站点/里程归一化、Excel 和文本编码辅助。工具函数应保持无副作用，不连接设备、不写数据库、不访问当前工作目录。

主要入口为各模块及其调用方测试；编码遵守 Windows 外部文本探测顺序。修改归一化或排序语义时运行对应 Python 定向测试。

## 用途与边界

本目录收纳无副作用的排序、接口/MAC/站点/里程归一化、Excel 和文本编码辅助；不连接设备、不写数据库、不读取当前工作目录。

## 主要入口

`text_encoding.py` 处理外部文本编码，`mac_utils.py`/接口与站点模块做归一化，`natural_sort.py`/`interface_sort.py` 提供排序，Excel helper 处理工作簿细节。

## 依赖关系

工具被 Parser、Service、Repository、Export 和 Web DTO 使用，优先依赖标准库/小型公共库；不得反向依赖业务 Service 或 UI。

## 数据与状态

函数输入输出为内存值或显式传入的文本/工作簿对象，不持有跨请求状态；文件读写由调用方传入受控路径并指定 UTF-8/回退编码。

## 测试与修改

修改排序、归一化、Excel 警告或编码回退时运行对应 Python 定向测试、parser fixture 和 Export 测试，补齐边界值。

## 生成与清理

工具本身不生成持久运行数据；Excel/文本输出由上层 Export/Service 管理，测试工作簿和临时文件使用 `tmp_path` 并清理。

## 相关文档

参见 [Windows 编码 Skill](../../../.agents/skills/windows-encoding-skill/SKILL.md)、[导出规范](../../../docs/export_process_policy.md) 和 [数据路径](../../../docs/DATA_LAYOUT.md)。
