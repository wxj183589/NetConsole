# H3C Comware V7/V9 Capability 审计

## 审计范围

本审计针对 H3C Comware 无线控制器与设备详情只读能力，目标是让已确认的 Comware V7、V9 设备按设备事实选择能力，同时保持未知 major、其他厂商和未知角色失败关闭。审计基线为本分支创建时的 `github/main@8f5d124e88fd5c69b564ad776994b53e60260b78`。

本次不包含 Huawei、ZTE、跨厂商 Adapter Framework、通用架构重构、SSH 传输重构或命令 Profile 平台扩展。

## 当前发现

| 区域 | 当前事实 | V9 风险 | 处理方向 |
| --- | --- | --- | --- |
| 版本 Parser | `src/netconsole/parsers/h3c/version_parser.py` 已解析 Comware 版本、major 和 Release；现有测试已有 V9 样例 | 实际 `Version 9.1.081, Release 1615P01` 尚未贯通能力选择 | 保留 V7 兼容，补足实际 V9 断言 |
| 设备事实 | `DevicePlatformFacts` 已包含 `software_version`、`software_major`、`software_release` | 事实可能为空时，下游不能猜测 V7 | 缺失 major 明确 unresolved |
| H3C resolver | 已支持 V7/V9，缺失 major 明确 unresolved | 版本事实必须先于能力计划 | 现场 bootstrap 后解析，unknown 不得默认 |
| AC Adapter | `H3cAcCommandProfile` 绑定现场 `DevicePlatformFacts` 后解析能力命令 | 旧调用没有把现场 `display version` 作为权威事实 | 已增加只读版本 bootstrap，再创建版本化 AC Profile |
| AC Collection | 已先 probe 再构造 AC Profile | 旧 V7 缓存不能遮蔽当前 V9 | 现场 probe 优先，probe 失败时失败关闭 |
| Device Collection | 已先执行 `display version` 再选详情 Profile | 版本事实顺序必须保持 | bootstrap 先于 H3C 计划选择，并保留原始日志 |
| Command catalog | `resources/device_command_profiles.json` 的详情 Profile 是通用只读 Profile，AC 命令由独立 Adapter 管理 | 文档容易把通用命令误写成 V7-only | 明确 common / V7-only / V9-only / optional 分类，不复制整套命令表 |
| Compatibility catalog | `resources/device_compatibility_profiles.json` 已有 V7/V9 方向登记 | 登记状态不能替代 resolver 和实机验证 | 以实际 resolver、Parser、采集测试和现场证据为准 |
| DTO/Query | `DevicePlatformFactsDTO` 已有 `software_release`，查询链路使用严格 DTO | 需要保持缺失字段为 `None`、不引入额外字段 | 增加/保留 V9 DTO 与 Query 回归 |

## 目标行为

1. H3C + Comware + V7 + `wireless_controller` 命中 `h3c_comware_v7_wireless_controller`。
2. H3C + Comware + V9 + `wireless_controller` 命中 `h3c_comware_v9_wireless_controller`。
3. V7 与 V9 复用已验证的只读 AC 命令和 Parser；不存在未经证实的 V9-only 命令。
4. 设备现场 `display version` 是本轮采集的最高优先级事实；旧缓存只作诊断/回退信息，不能覆盖现场 probe。
5. major 缺失、未知或不支持时不默认 V7，不执行依赖 H3C major 的能力计划。
6. Huawei、ZTE、未知角色和无 vendor 上下文均不能命中 H3C Profile。
7. 写操作（包括 SFTP enable）继续要求明确、受支持的 major 和既有受控 Profile，不因 V9 支持而放宽安全边界。

## Consumer Audit

- 写入方：H3C 只读 SSH collector 写入设备事实、AC 摘要、FIT-AP/Radio、LLDP/BSSID 和受控 raw log；本任务不修改 schema，不执行手工 SQL。
- 读取方：Device Detail Query、Device Compatibility、AC Query Service、FIT-AP/Radio/LLDP 展示与既有导出读取结构化事实；缺失字段保持空值语义。
- 缓存/旧数据：`device_facts` 与 AC 摘要可能保留历史 V7 事实；现场版本 probe 必须优先，未知时失败关闭，不能把旧 V7 作为当前 V9。
- 展示/API：DevicePlatformFactsDTO 严格建模 `software_version`、`software_release`、`software_major`、vendor、role、platform；不能出现 `ValidationError` 或将 V9 展示为 V7。
- 导出/Artifact：本次不新增导出格式；raw log 继续由现有采集路径保存，结构化结果沿用现有 Repository/Query 契约。
- 并行修改：主工作区 `main` 存在 Task/Event/Storage Registry/Settings 等未提交修改；与本任务隔离，本分支不包含、不覆盖、不解决这些修改。

## 兼容性与验证矩阵

| 场景 | 预期 |
| --- | --- |
| V7 fixture / 既有 V7 device | 保持原 family、命令顺序和解析结果 |
| V9 fixture `9.1.081 / 1615P01` | 解析 V9 与 Release，选择 V9 AC/详情能力 |
| 无软件事实、SSH 可用 | 先执行 `display version`；成功后再规划命令；不得变为 V7 |
| 无软件事实、SSH 不可用 | 明确 unresolved/连接错误，失败关闭 |
| 不支持 major | 拒绝对应 H3C capability |
| Huawei/ZTE | 不能命中 H3C capability |
| unknown role / 无 vendor | 不能 fallback 到 switch 或 H3C |
| sqlite3.Row / dict / 缺字段 | Query 保持兼容，缺失返回 `None`/默认 |

## Findings

1. **Fixed**：`resolve_h3c_capability()` 不再将缺失 major 默认成 V7，正式支持 V7/V9；这是实际 V9 设备进入 capability resolver 的必要修复。
2. **Fixed**：AC Profile 的能力命令现在在 SSH 版本 probe 之后生成，满足“现场事实优先、未知不猜测”的顺序要求。
3. **Confirmed**：现有 Parser、`DevicePlatformFacts`、严格 DTO 和部分兼容性资源已有 V9 基础，可在当前边界内复用，不需要新增跨厂商框架。
4. **Verified**：已补充“无缓存事实 -> `display version` -> V9 plan”的 mock bootstrap 回归，并在杭州地铁10号线 WX3540X/R1615P01 上完成真实只读采集与 API 查询。

## 结论

当前风险为 L2 领域能力变更，涉及 H3C Parser/Adapter/Collection/Device Detail/Compatibility 的直接消费者。已在本隔离分支内实施最小 V7/V9 capability 修复，并完成 AC、H3C resolver、Parser、Collection、Compatibility、Device Detail/Query、Ruff、compileall、diff check 和完整 Python/Renderer/Electron/Architecture 门禁。真实设备、API 和前端结果另见 `docs/development/H3C_COMWARE_V9_CAPABILITY_ACCEPTANCE.md`；未执行写操作，不以只读验收替代生产变更审批。
