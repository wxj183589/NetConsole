# SNMP 真实设备烟测

该目录只提供手工启用的真实设备烟测框架，普通 pytest 不连接设备。

1. 复制 `smoke_devices.example.yaml` 到工作区外的私有文件。
2. 填写测试设备地址和只读参数；团体字通过环境变量提供，不写入 YAML。
3. 设置 `NETCONSOLE_SNMP_SMOKE_CONFIG` 为私有 YAML 的绝对路径。
4. 运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\smoke\snmp
```

自动烟测只执行 GET、WALK、GETBULK。SET 必须在确认 OID 可写、影响范围和回滚方法后单独手工执行。
