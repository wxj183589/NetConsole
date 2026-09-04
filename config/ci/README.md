# CI baseline configuration

`baseline_failures.yaml` 保存当前已确认的精确 Python、Architecture 和 Ruff 债务。新发现失败，旧发现消失只报告 baseline shrink；禁止通配符、目录级忽略和全局 `continue-on-error`。
