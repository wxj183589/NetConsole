# NetConsole v1.5.16 Syslog 安全审计

状态：自动化契约 `PASS`；真实设备写入 `NOT PERFORMED`。

## 唯一来源

无人值守 Profile 的 Syslog server IP/port 同时驱动本地 UDP Receiver、只读检查、JOIN、EXIT、预览和状态展示。独立 Receiver 开关、独立监听地址和自动修复开关不再形成第二配置源。

## 检查

`GroundConfigCheckRequestDTO.mode` 默认 `VERIFY_ONLY`。检查路径只读取配置和运行态，不生成修复命令。人工 JOIN/EXIT 是独立入口并要求前端确认。

## JOIN 白名单

```text
system-view
info-center enable
info-center loghost <configured-ip> port <configured-port>
return
quit
```

`info-center source` 命令集合为空，测试断言不会隐式追加 source rule。

## EXIT 边界

EXIT 使用持久化的 NetConsole-owned 历史目标，而不是当前设置覆盖旧目标；只撤销精确 IP/port 的 loghost，不执行 `undo info-center enable`，不删除其他目标。

## 验证

- Syslog 安全集：31 passed。
- 所有配置写入均使用 Mock 连接；没有连接现场 MR。
- Comware V5/V7/V9 的真实只读/撤销回显仍需现场授权后的单设备验证，验证前不扩大批量写入范围。
