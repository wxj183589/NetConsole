# WPS AirScript Tools

WPS AirScript 辅助脚本目录，仅供显式用户操作或维护任务调用。脚本不属于 Backend 运行时入口，不写入业务数据根之外的运行目录。

标准连接探针与同步脚本是模板，`DOCUMENT_ID` 使用唯一的
`__NETCONSOLE_DOCUMENT_ID__` 标记。NetConsole 在用户从当前局点复制脚本时，
仅以已保存 webhook 的 `/file/<document_id>/script/` 身份渲染该标记；模板本身不包含任何局点文档 ID。

## Verification

修改脚本后运行对应的 Python 定向测试和编码检查。
