# 测试记录

- Renderer 定向 Vitest：2 文件、36 项通过，包含缓存身份、完整性、LRU 和工作台指标复用；API 使用模拟响应，不能证明真实 HTTP 或 SQL 零请求。
- `pnpm exec vue-tsc -b`：通过。
- `pnpm build`：通过，Vite 提示部分 chunk 大于 500 kB。
- 工作区目录检查：通过。
- 真实 API/SQLite 集成、100 次交互、真实图表实例稳定性和全指标实际数据正确性：未执行。
