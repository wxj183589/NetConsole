# 下载流程

设备文件下载提交现有 Task Center，保存任务 ID、opaque 远程条目引用、显示文件名、大小、进度、状态和错误码。Worker 负责 SFTP 读取、`.part` 临时文件、大小校验和原子替换；取消、失败、重试和断开均保留明确终态。

同名文件不静默覆盖，使用受控自动重命名策略。完成后通过 Electron Main 的受控 path reference 保存、打开文件或定位所在目录；后端不向 Renderer 返回本地绝对路径。
