# Interface Discovery Shadow 执行契约

日期：2026-09-04<br>
阶段：`PHASE 2D-A` 只读 Shadow 验证<br>
状态：已实现 Replay/注入式 Shadow Runner；未迁移生产入口，`PHASE2D_READY=NO`

本文记录 [interface.discovery 迁移契约](./interface-discovery-migration-contract.md)
的第一段可执行验证。它只证明同一份 normalized interface result 可以被旁路比较；
不授权替换 Legacy、不改变 `device.inventory.collect` 主流程，也不代表真实设备验收。

## 1. 范围和不变量

本阶段只处理单设备 Device Inventory 的接口事实：

```text
Legacy result (authoritative)
        │
        ├── existing DTO / Repository write (unchanged)
        │
        └── parallel read-only diagnostic
                │
                └── interface.discovery capability callback
                        │
                        └── existing Parser -> normalized result
                                │
                                └── interface DTO equivalence -> report/audit
```

不变量如下：

- Legacy Collector、既有 Parser、`DeviceFactRepository` 写入和用户可见结果不变；
- Runner 只接受一个已产出的 normalized result callback，不导入设备连接、Collector、
  Repository 或数据库；
- Shadow 不调用 `replace_device_interfaces`、`append_interface_history` 或任何其它
  Current/Recent/History 写入口；
- Shadow 失败、超时、空结果或差异都保留 Legacy 结果，不转化为 Legacy 任务失败；
- 不新增 Operation ID、DTO、API、UI、Feature Flag 或 Profile 配置；
- 不进入 Trackside、FIT-AP、Optical、LLDP、MR、MESH 或跨站点关联。

当前实现文件为
`src/netconsole/services/interface_discovery_shadow.py`。它是内部验证能力，不是生产
任务入口。

## 2. 调用顺序

`InterfaceDiscoveryShadowRunner.run()` 固定执行以下步骤：

1. 接收已完成的 Legacy status/result 和冻结的设备身份摘要；
2. 调用注入的 `shadow_capability`；
3. 要求 callback 返回包含 `interfaces` list 的 normalized result；
4. 对接口 collection 按既有 migration equivalence contract 去除运行态字段后比较；
5. 生成差异报告，并把只含安全摘要的 audit 交给可选内存 sink。

callback 是依赖注入边界。Replay 场景由现有
`tests/support/device_inventory_replay.py` 调用 H3C/ZTE Parser；Runner 不复制命令、
Collector、Parser 或 VLAN merge。未来若进入受控现场验证，连接、Profile、command guard、
超时和取消仍须由另行批准的 capability 实现负责；本阶段不建立设备连接。

## 3. 结果状态

`status` 始终是 Legacy status，因而 Shadow 不能改变任务权威结果。

| Legacy | Shadow | compare | `status` | 语义 |
| --- | --- | --- | --- | --- |
| `SUCCESS` | `SUCCESS` | `MATCH` | `SUCCESS` | 两侧接口 normalized facts 相同 |
| `SUCCESS` | `FAILED` | `SHADOW_FAILED` | `SUCCESS` | 旁路失败，仅记录诊断 |
| `SUCCESS` | `TIMEOUT` | `SHADOW_FAILED` | `SUCCESS` | 旁路超时，Legacy 不受影响 |
| `SUCCESS` | `EMPTY` | `DIFFERENT` 或 `MATCH` | `SUCCESS` | 空 collection 只与同样的空 normalized result 匹配，绝不写库 |
| `SUCCESS` | `SUCCESS` | `DIFFERENT` | `SUCCESS` | 生成差异，不自动修复或覆盖 Legacy |

Shadow callback 缺少 `interfaces`、返回非 list 或抛出其它异常时，Shadow 为
`FAILED`；`TimeoutError` 单独记为 `TIMEOUT`。Legacy status 不是 `SUCCESS` 时也照样
保留传入的 Legacy status，Shadow 诊断不能掩盖 Legacy 失败。

## 4. Normalized 比较

比较范围仅为 `interfaces` section，使用迁移契约定义的稳定接口字段和现有接口身份：

- 优先使用已有 `normalized_name`，否则使用已有 `interface_name`；不做 casefold、前缀、
  相似名称或跨设备猜测；
- 比较接口身份、category、状态、速率、双工、媒体、VLAN、描述、IP、MAC、last-change
  以及输入中已有的其它 normalized interface fields；
- 列表顺序和字段缺失语义保持输入 contract；缺失与 `null` 不强行视为相等；
- 只忽略既有 contract 的 runtime/source fields：raw、路径、时间、duration、session、
  collect/task metadata；
- 不读取 raw CLI 来重排或补齐，不比较命令文本、命令顺序、session、耗时或时间戳。

差异报告的 `added`、`removed`、`changed` 均为 JSON 数组。`changed` 按接口身份给出
字段级 Legacy/Shadow 值；字段缺失使用 `{"missing": true}` 表示。

最小报告形状如下（值仅为示例）：

```json
{
  "capability": "interface.discovery",
  "execution_id": "shadow-20260904-001",
  "device_identity": {
    "device_uuid": "device-1",
    "vendor": "H3C"
  },
  "status": "SUCCESS",
  "legacy_status": "SUCCESS",
  "shadow_status": "SUCCESS",
  "compare_status": "DIFFERENT",
  "authoritative_result": "LEGACY",
  "repository_write": "FORBIDDEN",
  "added": [],
  "removed": [],
  "changed": [
    {
      "identity": "interface_name=GigabitEthernet1/0/1",
      "fields": {
        "speed": {
          "legacy": {"missing": false, "value": "1G"},
          "shadow": {"missing": false, "value": "10G"}
        }
      }
    }
  ],
  "error": null
}
```

报告只序列化 normalized interface facts 和白名单设备身份；审计与异常摘要会去除
credential-like error value，不保存密码、token、community、username 或配置内容。

## 5. Shadow Audit 和存储保护

`ShadowAuditRecorder` 只在内存保存以下字段：执行时间、execution id、白名单设备身份、
Legacy status、Shadow status 和 compare status。它没有文件、SQLite、Current、Recent、
History 或 facts-version writer。

因此本阶段的 Repository effect 是固定的：

```text
Legacy writer calls       = unchanged
Shadow Current writes     = 0
Shadow Recent writes      = 0
Shadow History writes     = 0
facts/revision changes    = 0
```

空结果、超时和差异的回退动作都是丢弃旁路产物并继续使用 Legacy；不删除旧 current、
不重算 history、不创建第二个 interface recent 表。

## 6. Replay 与 CI 验证

Shadow 回归复用已有 Device Inventory Replay 和 fixture，不建立新 fixture 系统：

- H3C Comware 7 synthetic；
- H3C Comware 9 synthetic；
- ZTE ZXR10 5960X synthetic；
- 既有 Replay Parser contract、Golden 和边界测试继续独立运行。

测试文件为 `tests/test_interface_discovery_shadow.py`，覆盖匹配、失败、差异、超时、
空结果、runtime 字段忽略、报告序列化、敏感信息隔离和无 Repository/transport 边界。
现有 `.github/workflows/engineering-hardening.yml` 的 `python-regression` job 追加
该 Shadow 测试命令；没有新增 workflow，也没有更改其它 Python/Renderer/Electron gate。

Replay 通过只说明 Parser/normalized replay contract 在已纳入 fixture 的输入上稳定；
它不证明 H3C 现场版本覆盖、受控连接、GUI、生产数据库或生产迁移已经验收。因此
`PHASE2D_READY` 在本阶段仍为 `NO`。

相关契约：

- [Device Inventory migration equivalence](./device-inventory-migration-equivalence.md)
- [Device Inventory parser contract](./device-inventory-parser-contract.md)
- [Device Inventory snapshot contract](./device-inventory-snapshot-contract.md)
- [Interface Discovery migration contract](./interface-discovery-migration-contract.md)
