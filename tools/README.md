# NetConsole 开发工具目录

`tools/` 只用于开发、诊断、维护和协议分析工具，不是第三方运行时依赖来源。随包版本化的 fping/iPerf 唯一来源是 `resources/tools/`；禁止在 `tools/` 或 `apps/agent/tools/` 再放一份。

```text
tools/
└─ windows-x64/
   └─ ipop/
```

- `windows-x64/ipop/` 只保留 IPOP 外部工具说明；`IPOP.EXE` 由用户自行取得，仓库忽略该二进制，所有正式发布包均排除它。
- 用户也可在“系统设置 → 外部工具”配置任意本机绝对路径。
- 程序通过统一工具路径解析器定位文件，不依赖当前工作目录，也不回退旧版 Agent 工具目录。

仓库没有可核验的 IPOP 再分发许可。对外分发前必须取得并补齐许可证/NOTICE，否则不得把 `IPOP.EXE` 放入任何普通包、工程师包、安装包或 ZIP。
