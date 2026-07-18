# AP Identity 服务

本目录提供 AP/Radio/BSSID/Peer 的归一化模型、适配器和 resolver，用于只读 shadow/diagnostics 比较。当前不接管生产匹配、页面展示或业务结论。

主要入口为 `models.py`、`normalizers.py`、`adapters.py`、`resolver.py`；解析不确定性通过 matched/unresolved/ambiguous 和 confidence 表达。修改优先级时运行 AP Identity 测试与诊断检查。

## 用途与边界

本目录提供 AP/Radio/BSSID/Peer 的归一化、适配和 resolver，用于只读 shadow/diagnostics 比较；当前不接管生产匹配、页面展示或业务结论。

## 主要入口

`models.py` 定义模型，`normalizers.py` 处理 MAC/名称归一化，`adapters.py` 适配来源，`resolver.py` 计算候选与置信度。

## 依赖关系

身份服务被 AC、Mesh、轨旁 AP 和导出诊断调用，依赖解析后的领域记录而非设备连接；生产 Service 必须保留 legacy/shadow 边界。

## 数据与状态

输出带 matched/unresolved/ambiguous、confidence 和 diagnostics，不写入生产匹配字段；输入/比较结果由调用方决定是否进入报告或诊断表。

## 测试与修改

修改优先级、MAC/BSSID 归一化、候选判定或诊断字段时运行 AP Identity、AC/Mesh/Trackside shadow 和导出测试。

## 生成与清理

身份计算不生成独立运行目录；诊断/报告由上层 Export/Repository 管理，测试样本使用脱敏 fixture 和临时目录。

## 相关文档

参见 [AP Identity 总览](../../../../docs/AP_IDENTITY.md)、[展示评估](../../../../docs/AP_IDENTITY_DISPLAY_ASSESSMENT.md) 和 [重构地图](../../../../docs/REFACTOR_MAP.md)。
