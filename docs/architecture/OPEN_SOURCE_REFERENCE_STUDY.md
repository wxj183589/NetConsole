# 网络工程平台源码参考

审计基线为 NetConsole `7d423a73`。以下链接固定到实际读取的源码版本。此次采用设计和交互参考，不引入外部源码、服务或新依赖。

| 项目 / 技术架构 | 源码观察 | 对应产品决策与移植边界 | 许可证及分发条件 |
| --- | --- | --- | --- |
| [NetBox](https://github.com/netbox-community/netbox/blob/04bdbf464c380d2b4d1dc8d4f9c96fcc26f04981/netbox/dcim/models/devices.py)，Python / Django ORM | `Device` 关联 `DeviceType`、平台及部件，主 IP 与接口数量可由关系派生 | 设备档案使用同一稳定 ID 查询设备与采集事实。线路车站关系由组织结构维护。无需移植 Django ORM 或引入 CMDB | Apache-2.0 与 GPLv3 可兼容，分发源码时需保留归属及适用 NOTICE |
| [Oxidized](https://github.com/ytti/oxidized/blob/9ca3bc45322db62270038e2f821373da28bf2f2c/lib/oxidized/output/git.rb)，Ruby 输出插件 | Git 输出按 node/group 定位，`version`、`get_version`、`get_diff` 将采集与读取历史分离 | 配置采集保留当前快照、版本、差异契约，任务历史仅引用 Artifact。无需为每个局点新建 Git 仓库 | Apache-2.0，同样需核对 NOTICE 与依赖 |
| [eNMS](https://github.com/eNMS-automation/eNMS/blob/2e6042bae8087a3a1de2b6f48426edc3687660ee/eNMS/models/automation.py)，Python ORM 网络自动化 | `Service`、`Run`、`Result`、`ServiceLog` 分开建模，结果有过滤约束 | 任务模板、实例、每设备结果分别归属；执行参数留快照，后端先约束 Site。保留现有 Worker，不搬入工作流引擎 | GPL-3.0，移植需保留 GPL 分发和源码义务 |
| [Semaphore UI](https://github.com/semaphoreui/semaphore/blob/ca819f96750a7e43268633f10d983d5d8dda1ce5/db/Task.go)，Go 工作流与持久层 | `Task.ValidateNewTask(template)` 验证创建请求，`TaskStage`、`TaskOutput` 单独表达阶段和输出 | 设备任务重试创建新实例，进度与设备结果有独立身份。外部主机部署、Terraform 执行器不属于桌面产品 | MIT，分发需保留版权和许可文本 |
| [xterm.js](https://github.com/xtermjs/xterm.js/blob/196f7bca6f8c60137c8ee7dbfdbb7859c5b2fe7b/src/browser/Clipboard.ts)，TypeScript 终端组件 | `handlePasteEvent`、`prepareTextForTerminal` 和 `bracketTextForPaste` 集中换行及括号粘贴处理 | 确认在粘贴入口执行一次，保留完整文本，再交给已有终端输入链路。宏的暂停属于应用调度，不由剪贴板实现 | MIT，复用库时保留许可，实际锁定版本以项目 lockfile 为准 |
| [Netmiko](https://github.com/ktbyers/netmiko/blob/e033a517b87243322658310a9f8eb7047104321a/netmiko/base_connection.py)，Python 多厂商设备适配器 | `lock_channel` 串行化通道访问，`read_until_pattern` 有独立终止条件，`SecretsFilter` 过滤日志 | 继续复用已有适配层；单连接锁不能替代按 Site / Device ID 约束的跨任务调度。避免另写 SSH 实现 | MIT，保留许可证及归属 |
| [NetConsole](https://github.com/wxj183589/NetConsole/blob/7d423a73/src/netconsole/backend/api/main.py)，Python / FastAPI / Vue / Electron | `create_app` 组装设备详情、配置采集、文件、任务、无人值守等服务；路由聚合器注入 Feature 依赖 | 保留业务 Service、设备 ID 和局点库。Electron 持有原生文件/窗口权限，Renderer 使用受限 Bridge | 仓库 LICENSE 为 GPLv3；制品仍使用现有第三方许可清单 |

上表只评估所列文件及项目主许可证。若后续复制代码或改变依赖，需要核对具体版本、文件头、NOTICE、传递依赖及分发清单。
