v1.5.8 - 2026-09-13
### SSH/SFTP 现场运维自动恢复

- 统一普通 SSH、设备详情、设备操作、SFTP、SSH Relay 和隧道的 managed Host Key 策略：首次自动登记，
  变化按精确 host:port 原子替换并继续原业务操作；日志记录旧/新指纹，正常变化不再产生
  `TARGET_HOSTKEY_CHANGED` 失败终态。
- SSH 中转设置新增重新获取/删除当前跳板机指纹；设备文件移除 Host Key challenge 和 SFTP enable
  确认状态机，明确 SFTP subsystem 不可用时自动提交已验证 Profile、等待 Task Center 成功并自动重连。
- H3C Comware V7 SFTP Profile 统一支持 `wireless_controller` 及历史 AC 别名；未知厂商、认证失败、
  网络失败和无法确认 V7 仍不会执行 H3C 配置命令。

### H3C Comware V7/V9 Capability 完成收口与杭州地铁10号线真实验收

- 完成 H3C Comware V7/V9 capability：先执行版本事实探测，再选择 AC、FIT-AP、LLDP、BSSID 和设备详情只读命令；未知 major 不默认 V7，Huawei、ZTE 和无 vendor 上下文不会误命中 H3C Profile。
- AC Query Service 保持 `sqlite3.Row`、`dict` 及缺字段的兼容语义；`DevicePlatformFactsDTO.software_release` 契约贯通设备详情、兼容性和采集链路；H3C command reference 与 Resolver、Adapter、Parser、Collection、Compatibility、AC 回归测试同步完成。
- 杭州地铁10号线 `hzl10` 真实设备 `251-无线控制器-主`（`WX3540X`，Comware `9.1.081 / R1615P01`）识别为 V9，命中 `h3c_comware_v9_wireless_controller`；SSH/bootstrap、AC、Device Detail、FIT-AP、LLDP、BSSID、连接记录、只读 API、GUI 查看/刷新和正常重启恢复均 PASS，V7 回归 PASS。
- 既有自动化门禁：Python `4868 passed, 2 skipped`；Renderer `1301 passed`；Electron `298 passed`；Architecture `12/12`；`NEW_FAILURES=0`。
- Production rollback、storage registry、Production GC、Task Lifecycle 及相关维护门禁保持 `OUT_OF_SCOPE`，本功能未修改其代码、数据或失败隔离逻辑。

### v1.5.8 正式打包记录

- 修复 v1.5.8 安装包运行时更新日志资源漂移：`docs/CHANGELOG.md` 作为唯一人工维护源，构建时自动生成 `src/netconsole/docs/changelog.md`/包内资源，并由 API、Renderer 和包内 smoke 校验版本去重、顺序与内容一致性。
- 原发布准备提交：`0f94605dcbbd171491432944b6564895359e249c`；对应 `build-0-0f94605d` Full/Customer 制品已标记 `SUPERSEDED`，原文件保留且不得作为当前候选。
- v1.5.8 修复后重新生成 Full/Customer 候选；构建、版本/commit identity、`packaged_dirty=false`、NOTICE、SBOM、NSIS 解包、SHA-256、runtime changelog API 和 Full/Customer edition contract 均通过，`published=false`，未创建 tag 或 GitHub Release。
- Full / Customer 正式候选包已完成人工 Windows 安装验收，GUI 启动/运行验收通过，`v1.5.8 Installer Acceptance=PASS`；最终候选 SHA-256 与构建时记录保持不变，`Release Status=READY_FOR_RELEASE`。构建摘要和 manifest 保留构建时的 `PENDING` 原始事实，不改写历史构建记录。
- Production rollback、storage registry、Production GC、Task Lifecycle 及相关维护失败保持隔离并明确为 `OUT_OF_SCOPE`，本次发布准备未修改 Production 数据。

v1.5.7 - 2026-09-13
### Task Lifecycle、Task Event Retention、Ground 与 SQLite

- 收口 Task Center 当前/近期任务模型、`site_import` task authority、Task Detail、终态轮询、Operational Cleanup、Tombstone 与 Cleanup DTO contract。
- 完成 Task Event Retention：默认 7 天，支持 3 / 7 / 14 / 30 天，仅清理终态任务 `task_events`；活动任务、Online MR、Ground、Task summary、Result、Artifact、Log Center 和业务数据继续保护。
- 修复局点切换后 Ground 使用旧 site context 的问题；宁波10号线 → 宁波12号线、宁波12号线 → 宁波10号线及 reload/restart 验证通过。
- 修复 SQLite compatibility trigger 检查的幂等性，避免普通启动无条件 DDL 和无意义 WAL checkpoint 主文件重写。

### 验证

- Python：4868 passed，2 skipped；Renderer：1301 passed；Electron：298 passed；Architecture：12/12 PASS。
- `NEW_FAILURES=0`，Full Gate PASS。

v1.5.6 - 2026-09-13
### Task Lifecycle、Ground 与 SQLite 最终收口

- 收口 Task Center 当前/近期任务模型、`site_import` 切换局点后的 task authority、终态任务轮询、Task Detail 跨局点访问、从列表移除和 Operational Cleanup。
- 完成 Tombstone Contract、Cleanup DTO contract 及 Log / Artifact / Business Data 数据边界保护；普通 Task Lifecycle 不依赖 Production maintenance、rollback owner 或 Production gate。
- 完成 Task Event Retention 真实数据验证：默认保留 7 天，支持 3 / 7 / 14 / 30 天，仅清理终态任务的运行事件；活动任务、Online MR、Ground、Task summary、Result、Artifact、Log Center 和业务数据继续保护。
- 修复全局局点切换后 Ground 页面与 API 沿用旧局点的问题；宁波10号线 → 宁波12号线、宁波12号线 → 宁波10号线及重载验证通过。
- 修复 `tasks.db` 旧兼容检查每次无条件重建 trigger 导致的无意义 WAL DDL；兼容检查改为幂等语义比较，正常启动不再重复写入。

### 最终验证

- Python：4868 passed，2 skipped；Renderer：1301 passed；Electron：298 passed；Architecture：12/12 PASS。
- Full Gate PASS，`NEW_FAILURES=0`。

### 主线治理与工程质量

- 完成全部本地、GitHub、NAS、worktree 与 recovery 分支的逐项 Git 审计，只将仍缺失的功能语义适配到最新主线；已合入、补丁等价和受保护分支均未盲目回灌。
- 正式收录 E3 SSH 连接路径的长期离线契约与历史根因证据，保留首次真实设备复验失败的原始结论，不把离线测试冒充真实设备通过。
- 清零 Python、Architecture、Ruff 与版本策略的已知基线债务，并修正活动文档命名，使正式全量门禁恢复为零容忍。

### Ground、存储与现场诊断

- Ground Syslog 增加内存队列到受管磁盘 spool 的可靠落盘、重启恢复、容量保护与归档隔离，保持 Raw 先于解析和 SQLite 投影提交。
- 根据当前数据根所在卷选择保守或高速存储策略，统一 Raw 刷新、耐久同步和数据库批处理参数；识别失败时安全回退保守策略。
- 新增受管现场诊断包：只读采集当前局点和当前数据卷的有界证据，经 Task Center、Artifact 与用户另存流程导出；Raw 内容默认不采集，须用户明确选择。

v1.5.5 - 2026-09-09
### v1.5.5 SSH Relay 人工验收收口与 Production 包

- 新增局点级 SSH Relay / Jump Host：局点默认关闭，人工启用后，内部设备 SSH/Telnet 连接统一经过 `DeviceSSHConnectionFactory`，Relay 使用 Jump 的 SSH `direct-tcpip`。
- 设备管理、AC、车站交换机、轨旁 AP、FIT-AP、Optical 和 LLDP 等内部 SSH 路径统一复用站点 Relay；Jump 与目标设备凭据隔离，连接阶段错误分类和 Target Host Key/Authentication 处理完善。
- 核心现场人工验收已确认 PASS：Windows 安装运行、局点 SSH Relay、AC over Relay、车站交换机 over Relay、轨旁 AP over Relay 和轨旁光衰采集；Ping/ICMP、SNMP/UDP 不属于 SSH Relay 范围。
- 外部 SecureCRT/Xshell/PuTTY 终端和独立 Windows Agent 未纳入本次人工验收范围，继续单独标记为 NOT VERIFIED。
- Site SSH Relay Jump Host 改用受控 `AUTO_REPLACE`：首次自动登记，变化仅原子替换当前 host:port 并记录旧/新指纹；保存设置、Backend 启动和局点切换自动恢复 Relay，目标设备与 SFTP 的严格主机密钥策略不变。

### 局点级 SSH Relay 现场诊断与 FIT-AP 传输路径

- Target SSH 经 Jump 建连增加阶段化诊断、目标主机密钥受控 TOFU、主机密钥变更拒绝和目标认证失败收口；Jump 与 Target 主机密钥、账号凭据保持隔离，密码不写入日志。
- 轨旁 AP 车站交换机和 FIT-AP Optical 既有 Telnet 目标统一进入 `DeviceSSHConnectionFactory`；Relay 开启时直接使用 Jump 的 direct-tcpip Channel，Relay 关闭时保持 Direct，不创建每设备 localhost 端口映射。
- 保留 H3C 既有最小 `ssh-rsa` 兼容回退，不修改 AP 身份、轨旁业务规则、命令、解析器、光衰阈值或默认并发。

### AP 光衰业务状态统一

- 统一当前有效 AP Rx 的用户可见状态：Rx < -13.90 dBm 显示“光衰大”，Rx >= -13.90 dBm 显示“正常”。
- FIT-AP 光衰筛选统一为“正常 / 光衰大 / 无数据”，移除“偏低关注 / 一般告警 / 严重告警”等容易产生歧义的业务展示；设备原始告警等级仍保留用于诊断。

### 轨旁 AP 业务统计与数据边界

- 修复普通列表、仅业务光衰异常筛选和顶部统计的口径不一致，DETAIL / FILTER / SUMMARY 统一使用 Backend canonical optical authority。
- 仅当前有效采样参与 normal / abnormal 判断；stale、missing、unknown、collection_failed 不再使用历史 Rx 冒充当前异常，no_module、unsupported、not_applicable 等既有语义继续保留。
- 修复已有可信 AP/FIT 与当前 LLDP MATCHED 时因 identity unresolved 被错误排除的问题，并保持 raw module unknown 不否决已规范化的业务状态。

### Renderer 与概览展示

- 轨旁 AP 业务 Renderer 不再根据 Rx 二次计算 business abnormal，改为由 Backend canonical status 驱动 pre