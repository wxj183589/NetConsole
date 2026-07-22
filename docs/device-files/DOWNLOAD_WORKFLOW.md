# 下载流程

设备文件下载提交现有 Task Center，保存任务 ID、opaque 远程条目引用、显示文件名、来源设备、远程路径、真实受控目标路径、大小、进度、速度、状态和错误码。队列保持单并发顺序执行。Worker 负责 SFTP 读取、`.part` 临时文件、大小校验和原子替换；取消、失败、重试和断开均保留明确终态。

同名文件不静默覆盖，使用受控自动重命名策略。任务完成即表示文件已经写入真实目标目录，不存在
Artifact 二次保存。页面立即刷新当前本地目录、定位普通下载文件并更新批次汇总；“打开”和“所在目录”
由后端针对已完成任务签发一次性 opaque 桌面动作，Electron Main 只执行固定白名单动作。

首次恢复调用固定为 20 条。`TaskRepository` 在 SQL 层组合过滤 `task_type + owner + source + site +
status + limit/offset`，活动任务优先；下载 descriptor、hidden 和 waiting 事件按本批任务一次查询并聚合，
不会为了少量文件任务遍历其他模块历史或逐任务执行 `list_events()`。

目标路径由后端决定：

- 普通设备文件默认进入 `data/sites/<site>/downloads/files/<safe_device_name>/`；用户已进入其受控子目录时进入当前目录。
- 设备必须精确属于“车载-MR”分组并关联 MR Profile，且文件名命中 MESH 规则，才强制进入 `data/sites/<site>/rail_transit/mesh/<mr>/raw/`。
- MESH raw 原文件在自动导入失败时仍保留；不得因设备名称包含 `MR` 而推断身份。
