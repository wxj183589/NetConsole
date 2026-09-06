# Interface Discovery Limited Production Validation Plan

> Phase: `PHASE 2D-B PREPARATION`
> Status: `DESIGN_ONLY`
> Date: 2026-09-06
> Scope: interface discovery Shadow 的受控真实环境验证设计

## 1. 目的与结论边界

本文件定义 interface discovery Shadow 进入有限真实环境验证前的准备方案。它只描述如何取得可审计、可回滚、可归因的证据，不执行真实设备连接，不启用生产 Shadow，不改变现有采集结果、任务状态、UI 或数据写入路径。

Legacy Collector 仍是生产唯一事实源。Shadow 只能观察和比较：它不能写入 Current、Recent10、任何仍保留的 bounded `*_history`，不能改变 Repository、数据库 schema、API 响应或用户数据。当前阶段的结论是设计已完成，而不是已通过真实设备验收：

```text
PHASE2D_B_PREPARATION_STATUS=PASS
PHASE2D_B_READY=NO
```

本计划必须回答以下五个问题：

1. 在受控真实设备输出下，Shadow 是否稳定运行。
2. Legacy 与 Shadow 的 normalized DTO 是否一致。
3. Shadow 是否对生产流程、任务状态和用户可见结果零影响。
4. Shadow 执行前后 Repository 是否保持不变（Legacy 自身的预期写入须单独归因）。
5. 出现异常时，是否能停止 Shadow 并让 Legacy 继续，必要时按既有备份/恢复边界回滚。

### 1.1 Phase 2D-B1 rehearsal 状态

隔离回滚、Repository effect、备份清单、停启恢复和五类 Shadow 场景已在
[`interface-discovery-rehearsal-report.md`](interface-discovery-rehearsal-report.md) 中完成演练并记录结果。该报告只证明工程侧可运行、可停止和零 Shadow 副作用；不包含真实设备连接或生产启用授权。

## 2. 权威边界与前置 Gate

### 2.1 本计划使用的现有契约

- `docs/dev/interface-discovery-migration-contract.md`：Legacy-only 写入、比较字段、失败归因、回滚和 G1-G9 Gate。
- `docs/dev/interface-discovery-shadow-execution.md`：当前 Shadow Runner 的注入式执行、只读报告、`MATCH`/`DIFFERENT`/`SHADOW_FAILED` 比较语义。
- `docs/dev/device-inventory-migration-equivalence.md`：只比较 normalized DTO，不把 Raw、时间、session 或 task metadata 当作业务差异。
- `docs/dev/device-inventory-capability-inventory.md`：当前正式 Operation 仍为 `device.inventory.collect`；`interface.discovery` 只是候选能力，不得在本阶段升级为新的正式 Operation。
- `docs/dev/device-inventory-parser-contract.md` 与 `docs/dev/device-inventory-snapshot-contract.md`：Parser、Replay、空结果、部分结果和错误的既有边界。

### 2.2 进入有限验证前必须冻结的内容

在任何未来真实验证开始前，验证单中必须记录并冻结：

- NetConsole commit、构建身份、现有正式 Operation `device.inventory.collect`、设备 profile ID/版本和命令/selector 映射。
- 目标设备的 vendor、model、software version、role、设备负责人、维护窗口和既有 Legacy 采集入口。
- Legacy 与 Shadow 的同一设备关联标识；诊断报告可以使用现有任务/采集 run 的关联 ID，但不得新增正式 Operation ID。
- 预期的 Parser 状态、允许的空结果语义、报告保存位置、证据保留期限和访问人。
- 备份/恢复责任人、停止 Shadow 的操作人、异常升级路径及明确的终止时间。

进入 Gate 的最低条件为：`Replay PASS`、`Shadow PASS`、`Golden PASS`、`Contract PASS`、`Rollback PASS`、`Evidence Ready`。Phase 2D-B1 已完成隔离 rollback/effect/backup/evidence rehearsal；`PHASE2D_B_REAL_DEVICE_READY=YES` 仅表示工程 Gate 已就绪，真实设备验证和授权仍未完成，因此 `PHASE2D_B_READY` 与 `PHASE2D_READY` 继续为 `NO`。

## 3. 有限验证范围与设备选择

### 3.1 首批范围

首个 Limited Production Validation window 只覆盖 H3C，分别选取：

- 1 台具备合格维护条件的 H3C Comware 7 设备；
- 1 台具备合格维护条件的 H3C Comware 9 设备。

两台设备按现有单设备 worker 语义串行执行，不并发。每个版本最多一台，因此第一窗口上限为两台；这是为了覆盖已明确的 H3C 版本差异，同时让报告复核和人工回滚仍保持在一个可控维护窗口内。若某一版本没有合格设备，则该版本标记为 `EVIDENCE_NOT_READY`，不得用另一版本替代来宣称版本覆盖完成。

首批默认只选择已有 H3C switch profile 且有明确 owner 的角色。Wireless controller、mobile router 或其它 role 只有在对应 profile、命令证据、负责人和回滚条件分别审核通过后，作为独立后续窗口加入；不得在首个窗口混合扩大角色范围。ZTE、FIT-AP、Trackside AP、Optical、LLDP、MR、MESH 及全网/全厂商覆盖均不属于本阶段。

### 3.2 选择与排除标准

每台候选设备必须同时满足：

1. 低风险：不处于核心控制链路、重大施工切换、频繁配置变更或故障处置中。
2. 可维护：设备负责人在场或可即时响应，存在明确的维护窗口和停止 Shadow 权限。
3. 有历史依据：已有可追溯、合法的 Legacy inventory 结果，能建立本次前置 Current/Recent10/`*_history` 基线。
4. 有版本代表性：software version 与目标 Comware 版本一致，CLI 输出来源可说明。
5. 可回滚：既有备份/恢复方案已由负责人确认，异常时能先停止 Shadow 再恢复 Legacy-only。
6. 不改变生产意图：验证期间不得同时进行会影响接口、VLAN、速率、光模块或邻居输出的配置变更。

以下任一情况直接排除：无 owner、无稳定 Legacy 基线、版本/profile 未确认、无法保存安全证据、维护窗口不足以完成停止和检查，或设备连接/命令存在未审计的权限与影响风险。

## 4. Shadow Window 设计

### 4.1 触发方式与频率

Shadow 不创建独立 scheduler，也不创建新的后台任务。未来受控验证应挂靠在已有 `device.inventory.collect` 的一次冻结采集上下文中：先获得对应 Legacy 结果，再在同一设备、同一 profile/version 和同一 Parser 契约下执行一次只读 Shadow 比较。当前仓库并未授权将该设计接入生产默认采集路径；这只是后续验证 harness 的操作约束。

首个验证窗口对每台入选设备执行 3 个连续、可比的 Legacy inventory refresh cycle，每个 cycle 至多执行一次对应 Shadow。3 次是本计划的最小重复性样本：可以覆盖单次偶发连接/输出波动，又不会把首批范围扩成持续调度。周期沿用设备现有的、由 owner 批准的刷新节奏；不得为了验证新增 scheduler 或人为改变业务刷新频率。

### 4.2 运行时、窗口上限与任务影响

- 单次 Shadow 的硬边界不超过对应 Legacy refresh 已有的任务/命令 timeout budget；没有独立的无限等待。
- 整个窗口的硬停止时间是变更单中记录的维护窗口结束时间；缺少明确结束时间时，窗口不得开始。验证 harness 必须在结束前停止 Shadow 并完成检查，不得自动延长。
- Shadow 的连接、解析和报告不得改变 Legacy 的终态、错误、返回 DTO、任务进度或 UI 展示。若未来实现需要额外连接，其耗时必须在批准的 task budget 内；不能满足时立即停止并记为 `ERROR`。
- Shadow 失败只写入受控验证证据，不升级为 Legacy 失败；Legacy 失败也不能被 Shadow 成功掩盖。
- 失败记录使用本次验证的外部报告/审计文件，不写 Repository，不改变正式任务状态，不新增正式 Operation 或 Feature Flag。

### 4.3 窗口停止条件

出现以下任一情况，立即停止该设备及后续设备的 Shadow，仅保留 Legacy：Shadow timeout/exception、未解释的 `DIFFERENT`、Legacy 失败、任务超时、Repository fingerprint 变化、重复 history、用户可见状态变化、命令/权限超出冻结范围、设备进入配置变更或故障处置。停止本身必须有时间、操作者和原因记录。

## 5. 数据与证据采集

### 5.1 每个 cycle 的最小证据

每台设备每次 cycle 形成一份可关联的证据包，至少包括：

- device model、vendor、role、software version、profile ID/version；
- CLI output source（来源说明、命令名或既有受控引用；原始输出只在批准且脱敏后保存）；
- Legacy 与 Shadow 的 collection time、关联 run/task reference、执行顺序和状态；
- Legacy Parser 与 Shadow Parser 的 parse result、warnings、empty/partial/error 语义；
- Shadow Report，包括 compare status、normalized DTO projection 摘要和 field-level differences；
- 设备负责人、操作人、维护窗口、验证 harness/commit、停止原因（如有）；
- 运行前后 Repository read-only fingerprint 和 effect check 结果。

证据只保存验证所需的最小内容。不得保存 password、token、session secret、私钥或未经脱敏的敏感配置；不得把完整生产 Site、完整生产数据库或真实数据根复制到验证目录。需要引用既有输出时保存受控引用和 hash，不能以复制生产数据替代证据审计。

### 5.2 证据完整性

证据包必须能从“设备 + profile/version + cycle + collection time”唯一关联到 Legacy/Shadow 报告。报告缺少设备版本、CLI 来源、parse result、时间或 Repository 检查结果时，不能计入连续 MATCH 样本，只能标记 `EVIDENCE_NOT_READY`。证据保存位置、访问权限和保留期限在变更单中确定；本阶段不创建或写入生产证据。

## 6. Difference Determination

### 6.1 统一结果

验证报告对外只使用 `MATCH`、`DIFFERENT`、`ERROR` 三种结果；当前 Runner 的 `SHADOW_FAILED`、`TIMEOUT` 等内部状态在验证报告中归一为 `ERROR`。

| 结果 | 判定 | 处理 |
| --- | --- | --- |
| `MATCH` | Legacy 与 Shadow 的 normalized interface DTO projection 完全相等，包含 identity、行数/cardinality、字段值、空结果/状态语义；没有未解释的 Parser 或证据异常。 | 记录完整报告，允许进入下一次 cycle。 |
| `DIFFERENT` | 任一接口身份、数量、字段、状态、speed/VLAN 等契约字段不一致，或一侧有 added/removed/changed；报告必须列出 field name、old、new。 | 立即停止窗口，Legacy 结果保持权威，进入复核；不得自动修正或写库。 |
| `ERROR` | Shadow exception、timeout、invalid/unsupported 输出、证据不完整，或执行无法在既有 task budget 内完成。Legacy 失败也单独记录，不能被 Shadow 成功覆盖。 | 立即停止 Shadow；Legacy 继续作为唯一生产路径，并保留错误证据。 |

比较只针对合同规定的 normalized DTO。Raw output、命令文本本身、session、task metadata、collection time、duration 等运行字段不作为 DTO 差异；但命令/profile/版本、Parser、状态、证据和 Repository 分别作为独立 Gate 检查。合法的空结果不能仅凭“数量为零”判为成功：只有两侧空状态都符合契约才是 `MATCH`，一侧空或状态不明应为 `DIFFERENT`/`ERROR`。

### 6.2 有限窗口 PASS 标准

每台选定设备必须满足以下全部条件，窗口才可记为 `PASS`：

- 3 个连续、证据完整且可比的 cycle 均为 `MATCH`；
- Shadow `ERROR=0`，未解释的 `DIFFERENT=0`；任何一次异常均停止窗口，不用平均值抵消；
- 对应 Legacy cycle 无新增失败、无任务超时、无任务状态或 UI 可见结果变化；
- Shadow 相对 Legacy 的 Repository effect 为 0，且没有重复写入、revision 异常、history 非预期增长或 schema/file 变化；
- 3 个 cycle 的 profile/命令/Parser/版本和设备配置均未偏离冻结条件；
- 负责人完成报告复核和 rollback evidence review。

“3 个连续 MATCH”只证明这两台候选设备和冻结版本/角色在这个有限窗口内满足重复性，不代表全网、全厂商、全 role 或生产切换通过。

## 7. Repository Effect Checks

### 7.1 采集顺序

为了区分 Legacy 的既有写入与 Shadow 的影响，未来每个 cycle 必须按以下顺序做只读检查：

1. Legacy refresh 前：读取并记录 Current、Recent10 和仍保留的 bounded `*_history` 的计数、最新记录标识、source revision/fingerprint、相关任务状态及数据库健康信息。
2. Legacy refresh 后、Shadow 前：再次只读读取，记录 Legacy 自身预期的 current/recent/history 变化。
3. Shadow 完成后：使用相同只读检查重新读取；与第 2 步逐项比较，Shadow 预期 delta 必须为 0。
4. cycle 结束和窗口结束：复核所有目标设备的计数、revision、fingerprint、history 上限和任务状态，输出 effect check 结论。

若 Legacy 在第 2 步产生合法写入，只能把该 delta 归因到对应 Legacy run；不能把“最终数据看起来合理”当作 Shadow 无写入证据。

### 7.2 禁止的验证方式与 PASS 条件

验证 harness 只能使用现有只读查询、fingerprint 和报告导出；不得为 Shadow 直接打开 Repository writer、调用数据库写 API、插入/更新/删除任何 Current/Recent10/`*_history`，不得执行 schema/migration 或直接修改生产数据库文件。

Repository Effect `PASS` 要求：Shadow 前后 Current/Recent10/`*_history` 内容与计数无非预期变化；无重复写入、revision anomaly、history cap anomaly、task state 变化、schema/file 变化；所有变化均能归因到对应 Legacy cycle 或预先记录的外部维护动作。任何无法归因的变化都是窗口失败和停止条件。

## 8. 切换前备份设计（仅设计，不执行）

本阶段不创建、不复制、不恢复生产备份。只有在 Limited Validation 通过、另行批准未来切换并准备执行前，才按既有 storage governance 设计一次可恢复的 pre-switch backup manifest，至少包含：

- 当前发布 commit/build identity、正式 Operation/profile/Parser 版本和校验值；
- 设备 profile、命令/selector 映射、Feature registry 和运行配置快照；不得加入新的 Operation ID 或 Feature Flag；
- 设备元数据、Current/Recent10/仍保留的 bounded `*_history` 及相关 source revision/fingerprint 的只读清单；
- 受现有数据库治理约束的数据库快照、WAL/SHM 一致性处理和 `quick_check`/校验结果；不复制整个生产数据根；
- 活动任务、当前 Legacy writer、Shadow 状态、quiesce 状态、备份时间、负责人、恢复路径和验证结果；
- 版本化的回滚命令/步骤引用与恢复后检查项。

备份 manifest 不保存密码、token、私钥或敏感配置。备份设计不能被解释为本阶段已经完成备份，也不能成为未经批准的生产切换授权。

## 9. Rollback Rehearsal

### 9.1 演练顺序

回滚演练必须先在 Replay/isolated candidate 或明确批准的低风险验证环境完成；本阶段不连接真实设备、不执行生产演练。未来演练顺序固定为：

```text
建立 Legacy-only 基线
  -> 记录 Repository/task/UI fingerprints
  -> 仅开启已批准的受控 Shadow（当前没有新增开关授权）
  -> 执行一个 canary cycle
  -> 注入/等待异常（timeout、Parser mismatch、DIFFERENT 或 effect drift）
  -> 停止并禁用 Shadow
  -> 恢复 Legacy-only，继续既有采集
  -> 复核 task、Repository、用户数据和 Legacy 结果
  -> 如演练过写入切换，再按既有备份恢复并复核
```

演练不得修改默认 collection path、生产 Parser、DTO 或 Repository。若当前部署没有可关闭的受控 Shadow 入口，不得为演练临时新增 Feature Flag；应把该项记为 Gate blocker，并在另一个获批的实现任务中解决。

### 9.2 回滚 PASS 标准

演练 PASS 要求：Shadow 可停止且不会自动重启；Legacy 在停止后继续成为唯一来源；任务终态、任务耗时预算、UI 可见结果和用户数据与 Legacy-only 基线一致；Repository 无 Shadow 写入或不可归因变化；错误、操作人、时间和恢复结果均进入证据包。任一项失败都保持 `PHASE2D_B_READY=NO`。

## 10. 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
| --- | --- | --- | --- |
| command difference：冻结命令与真实设备 CLI 输出不一致 | 中 | 高：可能导致 Shadow ERROR 或错误差异，影响设备采集判断 | 首批按 H3C Comware 7/9 分版本选样；冻结 profile/命令；先 Replay/Golden，再由 owner 核对 CLI 来源；任何未解释差异立即停止。 |
| version difference：同一 Comware 主版本的小版本/补丁输出变化 | 中 | 高：normalized DTO 可能缺字段、误判或空结果 | 证据必须含完整 software version；每版本独立设备，不跨版本替代；版本未冻结则不计入 PASS。 |
| Parser difference：Legacy 与 Shadow 使用路径或 Parser 处理不一致 | 中 | 高：DTO 不一致或生产结果被误导 | Shadow 复用既有 Parser 契约并只比较 normalized projection；Parser/status 作为独立 Gate；不得在验证中修改 Parser。 |
| Shadow performance impact：额外连接/解析超过 Legacy 任务预算 | 低到中 | 高：任务超时、设备负载或 UI 状态变化 | 不创建 scheduler；每 cycle 至多一次；受既有 timeout 和批准窗口硬限制；超预算立即 ERROR、停止 Shadow、Legacy 继续。 |
| Repository anomaly：Shadow 误触发写入、重复 history 或 revision 漂移 | 低 | 严重：污染 Current/Recent10/`*_history` 或破坏用户数据 | Shadow 零 writer；前/Legacy后/Shadow后分段 fingerprint；只读 effect check；任意不可归因变化立即停止并按既有恢复方案处理。 |
| rollback failure：无法停止 Shadow 或恢复 Legacy-only | 低 | 严重：持续影响生产采集或用户可见结果 | 先 isolated rehearsal；预先指定停止/恢复责任人和结束时间；无通过的 rollback evidence 不进入 Limited Validation，更不进入任何切换。 |

## 11. Phase 2D-B Gate 与测试计划

### 11.1 Gate 状态

| Gate | 当前状态 | 说明 |
| --- | --- | --- |
| Replay | `PASS` | 既有 H3C Comware 7/9 等 Replay 证据可作为入口。 |
| Shadow | `PASS` | Shadow Runner 的只读、注入式执行和报告测试已完成。 |
| Golden | `PASS` | 既有 Golden/normalized equivalence 证据已完成。 |
| Contract | `PASS` | Migration、Parser、Snapshot 和 Repository 单写者契约已核对。 |
| Rollback | `PASS` | Phase 2D-B1 已完成隔离 MATCH、ERROR/TIMEOUT stop/resume rehearsal；真实设备仍未执行。 |
| Evidence Ready | `PASS`（隔离） | 已有 machine-readable rehearsal evidence schema、fingerprint 和 secret scan；真实 device/version/CLI/parse/report/effect evidence 仍待现场。 |

因此：

```text
PHASE2D_B1_STATUS=PASS
PHASE2D_B_REAL_DEVICE_READY=YES
PHASE2D_B_READY=NO
BLOCKERS=Real-device evidence; real-environment controlled stop/restore approval
```

### 11.2 本轮允许的检查

本轮只有文档变更，检查范围为：

- Docs/path guards：确认新增文档位于 `docs/dev/`、链接和 Markdown 结构符合仓库规则。
- Main contract smoke：在隔离的测试数据根运行既有主契约烟测；不使用或修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`。
- `git diff --check`：确认无空白错误。

若本地环境缺少既有依赖，只记录 `BLOCKED_LOCAL_ENV`，不为本阶段安装依赖，不连接网络设备，不改变锁文件。

### 11.3 明确禁止事项

本阶段禁止：

- 真实设备连接、生产 Shadow 启用或生产采集路径切换；
- 调用 `device.inventory.collect` 做真实验证、调用 Legacy Collector、Parser、DTO 或 Repository 写路径实施 Shadow；
- 修改 `resources/device_command_profiles.json`、新增 Operation ID、Feature Flag、API/UI 或任何采集实现；
- 扩大到 Trackside/FIT-AP/Optical/LLDP/MR/MESH、全网、全厂商或全 role；
- 打包、发布、版本修改或真实数据迁移。

## 12. 后续批准条件

只有当本文件的设备 owner、变更窗口、证据保留、Repository read-only 检查、isolated rollback rehearsal 和停止责任人均有签字/记录，并且 Gate 中 `Rollback` 与 `Evidence Ready` 从 `NOT_READY` 变为 `PASS`，才可另行提出 Limited Production Validation 执行请求。执行请求必须再次确认 Legacy-only 事实源、Shadow observe-only、零 Repository 写入和可停止；本文件本身不授予生产执行权限。
