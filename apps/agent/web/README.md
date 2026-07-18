# Agent 内嵌 Web

本目录包含 Go Agent 内嵌的静态 Web 页面和嵌入入口，用于查看 Agent 状态与执行受控操作。它不是 NetConsole 的 Vue Renderer，也不得复制 Python 业务逻辑。

主要入口是 `index.html`、`app.js`、`style.css` 和 `embed.go`；页面只能调用 Agent 已定义的 HTTP API。修改后运行 Agent 测试并检查嵌入资源构建。
