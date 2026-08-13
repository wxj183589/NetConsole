# 设备厂商导入与采集能力

设备资料导入与采集驱动是两个独立阶段。`Device.device_vendor` 保存用户填写的原始厂商文本，导出和再次导入时不改写该值；`Device.vendor_key` 由 `normalize_device_vendor_key()` 派生，仅用于驱动匹配。已登记别名（例如“华三”、H3C、“华为”、Huawei、“兆越”、Mexon）共享稳定 key，无法识别的文本使用 `unknown`，绝不因此套用其他厂商驱动。

## 导入边界

CSV/Excel 只校验厂商非空、长度和控制字符。Huawei、华为、Mexon、兆越及其它未知文本都可以入库、编辑、分组、筛选、导出和再次导入；正式 28 列、历史 21 列以及旧模板继续复用原有字段映射。导入预览同时返回 `collection_supported_rows` 与 `collection_unsupported_rows`，后者表示资料有效但当前没有采集能力，不计为导入失败。

## 驱动解析

`resolve_device_collection_support()` 在任何 SSH/SNMP/CLI 命令之前执行。它按 `vendor_key`、设备类型和版本化 Command Profile 返回 `supported`、`driver_key`、`reason_code` 与说明：

- `SUPPORTED`：明确匹配到 H3C/ZTE 的已登记 Profile。
- `UNSUPPORTED_VENDOR`：厂商没有驱动。
- `UNSUPPORTED_DEVICE_TYPE`：厂商已知但设备角色没有驱动。
- `UNSUPPORTED_COMMAND_PROFILE`：角色已知但没有可靠命令模板。

解析失败关闭，不会回退到 H3C、ZTE 或“最接近”的 Profile。新增厂商时先在 `resources/device_command_profiles.json` 注册经过验证的 Profile，再将其 vendor key 接入解析器；历史设备不需要重新导入。

## 任务状态

未适配设备使用 `status = SKIPPED` 并携带机器可读 `reason_code`。单设备刷新在启动网络连接前直接返回跳过；混合批量任务只为支持设备创建任务，跳过项不占 SSH 并发、不重试、不计失败数，也不修改已有事实或在线状态。前端以中性标签“暂未适配采集”显示，区别于连接失败、离线和“暂停使用”。

未支持采集并不代表设备无效，也不代表设备离线。设备仍可正常导入、维护、导出和参与基础资料管理。
