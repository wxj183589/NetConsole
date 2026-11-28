# 旧版 UI Electron 截图索引

真实 Electron 源码运行，演示局点，独立 `isolated_test` 数据根。CDP 设置应用视口，PNG 文件头核对像素尺寸。横向溢出列分别记录页面根与主工作区的 scrollWidth 与 clientWidth 差值。

| 页面 | 1920×1080 | 2560×1440 | 两档横向溢出 |
| --- | --- | --- | --- |
| 主窗口 | [1920×1080](../../../reports/tests/legacy-ui-ux/01-window-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/01-window-2560x1440.png) | 0 px / 0 px |
| 侧栏 | [1920×1080](../../../reports/tests/legacy-ui-ux/02-navigation-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/02-navigation-2560x1440.png) | 0 px / 0 px |
| 首页 | [1920×1080](../../../reports/tests/legacy-ui-ux/03-home-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/03-home-2560x1440.png) | 0 px / 0 px |
| 设备管理 | [1920×1080](../../../reports/tests/legacy-ui-ux/04-devices-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/04-devices-2560x1440.png) | 0 px / 0 px |
| 设备详情 | [1920×1080](../../../reports/tests/legacy-ui-ux/05-detail-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/05-detail-2560x1440.png) | 0 px / 0 px |
| 任务中心 | [1920×1080](../../../reports/tests/legacy-ui-ux/06-tasks-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/06-tasks-2560x1440.png) | 0 px / 0 px |
| 无线管理 | [1920×1080](../../../reports/tests/legacy-ui-ux/07-wireless-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/07-wireless-2560x1440.png) | 0 px / 0 px |
| 轨道交通 | [1920×1080](../../../reports/tests/legacy-ui-ux/08-rail-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/08-rail-2560x1440.png) | 0 px / 0 px |
| 轨旁 AP | [1920×1080](../../../reports/tests/legacy-ui-ux/09-trackside-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/09-trackside-2560x1440.png) | 0 px / 0 px |
| 控制台 | [1920×1080](../../../reports/tests/legacy-ui-ux/10-console-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/10-console-2560x1440.png) | 0 px / 0 px |
| 文件管理 | [1920×1080](../../../reports/tests/legacy-ui-ux/11-files-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/11-files-2560x1440.png) | 0 px / 0 px |
| 日志中心 | [1920×1080](../../../reports/tests/legacy-ui-ux/12-logs-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/12-logs-2560x1440.png) | 0 px / 0 px |
| 网络工具 | [1920×1080](../../../reports/tests/legacy-ui-ux/13-network-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/13-network-2560x1440.png) | 0 px / 0 px |
| 任务弹窗 | [1920×1080](../../../reports/tests/legacy-ui-ux/14-dialog-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/14-dialog-2560x1440.png) | 0 px / 0 px |
| AC 管理 | [1920×1080](../../../reports/tests/legacy-ui-ux/15-ac-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/15-ac-2560x1440.png) | 0 px / 0 px |
| 地面实时采集 | [1920×1080](../../../reports/tests/legacy-ui-ux/16-ground-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/16-ground-2560x1440.png) | 0 px / 0 px |
| 配置采集 | [1920×1080](../../../reports/tests/legacy-ui-ux/17-config-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/17-config-2560x1440.png) | 0 px / 0 px |
| 任务执行设置 | [1920×1080](../../../reports/tests/legacy-ui-ux/18-task-settings-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/18-task-settings-2560x1440.png) | 0 px / 0 px |
| 设备文件传输（SFTP） | [1920×1080](../../../reports/tests/legacy-ui-ux/19-sftp-1920x1080.png) | [2560×1440](../../../reports/tests/legacy-ui-ux/19-sftp-2560x1440.png) | 0 px / 0 px |

侧栏、设备详情、本地文件双栏和 SFTP 页已在 `16eca155` 上补拍，两个尺寸均通过。[8 张补拍测量](../../../reports/tests/legacy-ui-ux/capture-02-navigation-05-detail-11-files-19-sftp.json)

最终采集运行在 `2a286abb` 的源码工作区，应用标记为 dirty。首页显示设备总数 5、在线 AP 2、已汇报控制器 1。组织结构来自 `/rail-transit/infrastructure`，本地文件来自 `/file-manager` 双栏。文件右栏 HTTP 服务未初始化。运行日志非空，截图显示 20 条。任务弹窗实际展开执行设置。文件目录为空，未执行传输。

脚本实际导航到各页面，从档案列表打开 SW01 并切换到接口页，在任务中心打开创建设备任务弹窗。首轮 2K 档案点击命中隐藏缓存项，限定可见项后补拍通过。主窗口与侧栏以设备管理为上下文。页面根测量不覆盖表格内部滚动、文字裁切和控件遮挡。

本轮未执行设备连接、真实任务提交、安装态验收和其余业务弹窗的逐项操作。

## 复现

从 `apps/desktop_electron` 启动隔离运行。

```powershell
$env:NETCONSOLE_DEV_PORT = '5192'
$env:NETCONSOLE_DEVTOOLS_PORT = '9346'
$env:NETCONSOLE_PYTHON = 'D:/study/NetConsole-Workspace/NetConsole/.venv/Scripts/python.exe'
node scripts/dev.mjs --codex
```

启动完成后用 Node 执行 [截图脚本](../../../reports/tests/legacy-ui-ux/capture.cjs)。[首批 36 张测量](../../../reports/tests/legacy-ui-ux/capture-all.json)与补拍索引合计覆盖 19 个场景。
