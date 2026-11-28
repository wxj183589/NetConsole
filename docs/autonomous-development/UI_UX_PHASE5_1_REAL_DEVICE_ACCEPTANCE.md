# Phase 5.1 实验设备验收

| 设备 | 验收结果 |
| --- | --- |
| AC | SSH 只读版本及两次配置采集成功。每次基线采集产生 running、saved、diff。集成后 Electron 任务复用同类型最新版本 4、5、6，并提供规范化内容和字节 SHA-256 |
| SW | SSH 22 端口可达，指定认证失败。Electron 重试再次失败 |
| FIT-AP | 开启实验 AC 的远程控制台后，现有 Telnet 终端登录成功并返回 Comware 版本。配置任务将 Cloud-AP 标为跳过，未完成该设备配置采集 |

三设备任务 `device-task-a065b1f826b64623ab1c196f01ed9e04` 的业务状态为 `PARTIAL_SUCCESS`。重试 `device-task-ac28c27e060b4bc0820a100b34ca381b` 的业务状态为 `FAILED`，只含 SW，且保存来源任务 ID。

AC 回读的 running 与 saved 文件各 4,976 字节，字节 SHA-256 为 `4923fc161eaa9318bf5b58ac07fbbe21dd7a5570bfe583ac9a208888cbd5e3a6`。规范化内容 SHA-256 为 `30fef91f071aa9468ff61864556254549bee344bd2b5a256f583cc381071eab2`。真实样本内容相同，没有刻意改设备来制造变化。未执行保存或升级。
