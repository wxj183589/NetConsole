# 轨旁 AP AC 侧 LLDP 交换机身份调查

> 历史现场证据：本文冻结 2026-08-06 的脱敏数量口径和冲突降级依据，不是当前实现规范。当前规则以轨旁 AP 领域模型、AP Identity、生产代码和测试为准。

## 现场结论

只读检查现场局点数据库时，358 个在线 AP 均有可用运行态关系；其中 324 个已经由
交换机侧 `device_lldp_neighbors` 的 AP MAC 精确证据关联，另 34 个只在
`ac_fit_ap_resources` 保存了 AC 侧 LLDP 上联交换机名称。34 个 AP 并非缺少逐站 AP
规划：对应站点已有有效规划，AC 侧 LLDP 名称也都能唯一命中同局点 ZTE 交换机的
`devices.system_name` 或 `device_facts.sysname`。

调查过程只读取正式数据库，没有执行初始化、采集、更新或回写；本文不记录真实
管理地址、设备名或 MAC。

## 原错误链

```text
FIT-AP 在线资源
  -> 基础 AP MAC 未命中
  -> 只查询交换机侧 LLDP 的 AP MAC
  -> 34 个 AP 无交换机侧记录
  -> lldp_snapshot_stale / 待关联
  -> 页面统一显示为未关联 AP 规划
```

原 `EffectiveTracksideApScope` 不读取 AC 资源上的 `lldp_neighbor_name/mac/interface`，
也没有“AC 侧 LLDP 交换机身份 -> 设备管理交换机 -> 正式站点 -> 逐站规划”的路径。
设备管理“详情更新”会采集并写入交换机侧 LLDP，使 `lldp_revision` 变化；下次业务
查询重建后，34 个 AP 才通过原有 `switch_lldp_exact` 路径恢复。临时恢复来自新 LLDP
事实，不是按钮清理了特殊缓存，也不是 AP 规划被补写。

## 修复链

```text
基础 AP MAC / 交换机侧 AP MAC（原优先路径）
  -> 未命中且 AC 侧 LLDP 身份存在
  -> 当前局点交换机身份唯一解析
  -> 交换机 station_id；缺失时唯一正式站名解析
  -> 当前逐站 AP 规划校验
  -> ac_lldp_switch_identity 只读运行态投影
```

交换机身份优先级为稳定 UUID、唯一 Chassis/MAC、唯一管理地址、唯一规范化 system
name、明确设备别名。规范化只处理 Unicode NFKC、空格/大小写、FQDN、连字符/下划线
和 ZTE/ZXR10/H3C/Comware 前缀；任何字段命中多个当前局点设备时返回冲突。

## 自动恢复与一致性

轨旁业务页没有长期持久化的正式快照。每次查询读取来源 revisions（R1），构建完整
投影，再读取 R2；R1/R2 不同就丢弃并重试，成功结果才发布。来源指纹已覆盖
FIT-AP、逐站规划、基础资料、`devices`、`device_facts`、`device_interfaces`、交换机
LLDP、光衰和 AP Identity。

上线概览使用 revision-keyed 内存缓存，本次将交换机设备、facts 和接口身份变化加入
revision。AC/FIT-AP 采集、交换机 LLDP、设备详情/facts、规划或站点资料成功提交后，
下一次查询都会自动 miss/rebuild。不存在把刷新代码绑定到 ZTE 详情按钮的第二套路径。

## 回归口径

- 单元场景：324 条交换机侧 LLDP + 34 条 AC 侧 LLDP，修复前为 324/34，提供唯一
  交换机身份后收敛为 358/0，不调用详情更新。
- 应用场景：AC 侧 LLDP 已存在、交换机 sysName 后到达；写入 `device_facts` 后 revision
  变化、上线概览缓存失效，AP 自动进入已关联上线。
- 冲突场景：同局点同 system name 两台交换机时保持
  `SWITCH_IDENTITY_AMBIGUOUS`，不选择第一条。
- 数据兼容：不新增 schema，不修改 AP Identity 或 H3C 派生 MAC，不写回正式关系。
