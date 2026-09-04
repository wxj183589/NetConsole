# Device Inventory Command Replay Design

日期：2026-09-04
Phase：2B Device Inventory Command Replay Harness
Branch：codex-A/engineering-hardening
基线 HEAD：acbf15034bc9080c07a4231333b39eb3346f73b8

## 1. 目标和非目标

本阶段只建立 Device Inventory 的 CLI 输出回放和 golden regression 能力，验证：

~~~text
CLI fixture
  -> replay runner
  -> 当前已有 Parser
  -> test-only normalized result
  -> golden snapshot
~~~

验证重点是已有输出能否继续被正确解析，不验证命令能否连接或执行。

本阶段明确不做：

- 不修改 device.inventory.collect 的生产调度或执行；
- 不修改 Command Profile resolver 或 resources/device_command_profiles.json；
- 不修改 SSH/Telnet、Adapter、Parser 业务逻辑、DTO、API、DB、UI；
- 不新增生产 Operation；
- 不连接真实设备，不读取或写入 Production/Dev real data；
- 不把 synthetic fixture 或离线回放提升为真实设备兼容性结论。

## 2. 生产路径保护证明

### 2.1 当前生产路径

当前 Device Inventory 生产链路保持：

~~~text
POST /devices/{device_uuid}/refresh
  -> DeviceDetailApplicationService.refresh
  -> DeviceOperationService.start
  -> resolve_device_operation_profile
  -> BackgroundJob(task_type="device_detail_collect")
  -> run_device_inventory_refresh
  -> collect_h3c_device_details
  -> profile-selected SSH/Telnet command execution
  -> existing H3C/ZTE Parser
  -> DeviceFactRepository / DeviceRepository
  -> DeviceDetailDTO and device detail query
~~~

事实来源：

- API/Application：src/netconsole/backend/api/device_management_router.py、src/netconsole/application/device_detail.py；
- Operation/Job：src/netconsole/services/device_operation_service.py、src/netconsole/services/job_center/handlers/device_jobs.py；
- Collector：src/netconsole/services/h3c_collect_service.py；
- Profile/guard：resources/device_command_profiles.json、src/netconsole/services/device_command_profile_service.py、src/netconsole/services/command_guard.py；
- Parser：src/netconsole/parsers/h3c、src/netconsole/parsers/zte、src/netconsole/adapters/h3c/h3c_parser.py；
- Repository：src/netconsole/repositories/device_fact_repository.py。

本阶段不向这条链路插入 replay 分支，不改变调用顺序、命令、profile binding、连接方式、写入和错误处理。

### 2.2 Replay 路径

本阶段新增的测试路径是：

~~~text
tests/fixtures/device_cli/*.json
  -> tests/support/device_inventory_replay.py
  -> existing H3C/ZTE Parser functions
  -> test-only stable dictionary normalization
  -> tests/golden/device_inventory/*.json
  -> pytest assertions
~~~

Replay runner 只读取 fixture 文件和内存字符串：

- H3C 复用现有 parse_device、parse_sysname、parse_boot_loader 和 H3CParser；
- ZTE 复用现有 parse_device_identity、parse_interfaces、VLAN parser、parse_optical_summary、LLDP brief/entry parser 和 merge functions；
- runner 不导入 collector、DeviceFactRepository、SSH/Telnet transport、Task Runtime 或 API；
- runner 不创建数据库、collect run、raw log、session id 或临时生产路径。

因此，Replay 不调用：

- SSH；
- Telnet；
- Netmiko/Paramiko connection；
- 真实设备；
- Device Inventory 生产 Collector；
- Trackside/FIT-AP/MR/MESH 链路。

### 2.3 生产路径零变化门

本阶段完成时必须满足：

1. production source files 的 git diff 为空；
2. resources/device_command_profiles.json 的 git diff 为空；
3. Replay 测试只导入已有 Parser，不创建 ReplayParser/TestParser/MockParser；
4. Replay 失败只能阻止测试，不会阻止或改变生产采集；
5. 本阶段提交的测试输出不写入 D:/NetConsoleData 或 D:/NetConsoleData-dev。

## 3. Fixture 目录和来源标记

目录：

~~~text
tests/fixtures/device_cli/
  h3c_comware7_synthetic.json
  h3c_comware9_synthetic.json
  zte_zxr10_5960x_synthetic.json
  zte_zxr10_c89e4_real_redacted.json
  h3c_comware9/
    display_*.txt
  zte_lldp_neighbor_brief_small.txt
  zte_lldp_entry_small.txt
~~~

每个 JSON case 必须包含：

- fixture_id；
- operation_id，且本阶段只能是 device.inventory.collect；
- fixture_type，值只能是 REAL_CAPTURE 或 SYNTHETIC；
- source_note；
- vendor、role、platform、software_version；
- profile_id；
- outputs selector 到文件或 inline text 的映射。

来源规则：

- REAL_CAPTURE：仅用于已有脱敏现场采集片段，并记录覆盖的具体命令；不从局部 capture 外推整套设备能力；
- SYNTHETIC：手工编写或既有测试样例，必须明确不是真实设备证据；
- 禁止把 SYNTHETIC 写成 REAL_CAPTURE；
- 禁止提交 password、community、token、secret、真实账号、公网地址、真实敏感 IP 或用户目录；
- 文档保留的 192.0.2.0/24 为 RFC 5737 文档地址；测试 MAC、设备名和序列号均为 synthetic/redacted 标识。

本批 fixture：

| Case | 来源 | 范围 | 说明 |
| --- | --- | --- | --- |
| h3c-comware7-synthetic-s6850 | SYNTHETIC | H3C Comware 7.1.070 | 复用仓库既有 H3C parser 样例，不作为现场证据 |
| h3c-comware9-synthetic-s9850 | SYNTHETIC | H3C Comware 9.1.081 | 最小版本/身份/接口/DOM/LLDP 输出形状 |
| zte-zxr10-5960x-synthetic | SYNTHETIC | ZTE ZXR10 5960X-ES V2.00.20.03 | 复用既有 ZTE 文档样例，覆盖 VLAN、DOM 和 LLDP merge |
| zte-zxr10-c89e4-v1.9.0-real-redacted | REAL_CAPTURE | ZTE ZXR10 C89E-4 V1.9.0 | 复用既有脱敏现场片段，只覆盖 version/interface/optical 三条已存在输出 |

首批只覆盖 device.inventory.collect，不扩展 Trackside、FIT-AP、MR、MESH。

## 4. Replay Runner 设计

入口函数：

- load_fixture：读取 case metadata 和 file/text output；
- replay_fixture：从 JSON case 加载后回放；
- replay_case：按 H3C/ZTE vendor 分派到已有 parser；
- test-only normalization：去掉 raw line、parser metadata、时间和运行态字段，只保留用于 golden 的稳定字段。

Runner 的边界：

- 不执行 command；
- 不通过 profile resolver 选择命令；
- 不模拟连接成功；
- 不写 Repository；
- 不生成随机 UUID、时间戳、session、临时路径；
- 不实现任何新的 Parser。

H3C 回放覆盖：

- identity/version/device/manuinfo/sysname/boot-loader；
- interfaces；
- transceiver、manufacture info、diagnosis merge；
- LLDP list/verbose。

ZTE 回放覆盖：

- version identity；
- interface brief；
- switchvlan config 与 VLAN table 的既有 merge；
- optical brief；
- LLDP brief 与 entry 的既有 merge。

test-only normalized result 不是生产 DTO，不改变 DeviceFactDTO、DeviceDetailDTO 或其它 API contract。

## 5. Golden Snapshot 规则

Golden 文件位于 tests/golden/device_inventory/，文件名与 fixture case 一一对应。

Golden 只保存：

- fixture identity 和 source category；
- operation/profile/parser contract 标识；
- 稳定 device facts；
- interface、optical、LLDP 的稳定字段；
- parser status 和 warning count；
- ZTE VLAN 列表只保存 count/first/last，避免把展开后的大范围 VLAN 当成随机或业务快照。

Golden 不保存：

- 随机时间；
- uptime 采集时刻；
- collect run UUID；
- SSH/Telnet session；
- raw log 临时路径；
- 连接耗时、页数和运行机器路径。

更新规则：

1. 测试失败时禁止自动 update snapshot；
2. 任何 golden 变化必须先定位为 parser bug fix、已批准字段新增、fixture 修订或业务契约变化；
3. 变化说明必须进入同一提交或审查记录；
4. 不能为了绿色测试删除字段、放宽断言或覆盖 golden；
5. 真实 capture 的变化必须保留来源和覆盖命令，不与 synthetic 结果混淆。

## 6. 必须覆盖的等价验证

- CASE 1：每个 fixture 经已有 parser 回放并与 golden 完全一致；
- CASE 2：同一 fixture 连续回放两次，结果 JSON 结构和值完全一致；
- CASE 3：H3C/ZTE 空输出不崩溃，返回既有 parser 可表达的 EMPTY/NOT_RECOGNIZED/PARSE_FAILED 等状态；
- CASE 4：版本、接口、optical、LLDP 中出现异常格式时，parser 不把异常传播为 runner 崩溃；
- CASE 5：增加未知 output selector 时，既有 normalized result 不变化；
- CASE 6：fixture metadata 的路径越界、未知 source type 或非 inventory Operation 被拒绝；
- CASE 7：测试源码检查 runner 不包含 connection import，不引用生产 Collector/Repository。

## 7. CI 集成边界

Replay tests 稳定后，作为现有 .github/workflows/engineering-hardening.yml 的 python-regression job 中一个普通 pytest step 执行：

~~~text
python -m pytest tests/test_device_inventory_replay.py -q --tb=short
~~~

不新增 workflow，不新增服务、不新增真实设备依赖。Python regression 仍由已有 Windows/Python 3.13/locked requirements job 提供环境。

本机若缺少 Python 3.13 或 pytest，只能记录 BLOCKED_LOCAL_ENV；不得伪造 PASS。CI 通过也只证明离线 parser replay，不证明真实设备、GUI、安装、发布或现场拓扑。

## 8. 退出条件和后续

Phase 2B 可以报告 PASS 的最低条件：

- 4 个 case、1 个 REAL_CAPTURE、3 个 SYNTHETIC；
- H3C Comware 7/9 与 ZTE 现有 parser 均被调用；
- golden snapshot 全部通过；
- 空输出、异常格式、未知字段和重复回放通过；
- production path source/profile diff 为空；
- replay、main contract smoke、docs/path guards 的执行状态如实记录；
- DataRoot、真实设备和版本/制品状态未被触碰。

后续若要支持更多真实版本，应新增明确来源和脱敏审查，不扩展 fixture 数量来制造“兼容性覆盖率”。任何生产 profile、Operation 或 parser 变更仍需独立评审和真实设备门禁。
