# MESH 第七轮回归结果

| 检查 | 结果 |
|---|---|
| Renderer MESH 相关测试 | 33 files / 341 passed |
| Python MESH、AC-MESH、identity/rebuild | 495 passed / 3 warnings |
| `pnpm run build`（Renderer） | PASS；保留既有大 chunk warning |
| `pnpm run build:main`（Electron） | PASS |
| `pnpm run typecheck`（Electron） | PASS |
| `pnpm exec vue-tsc -b` | PASS（包含在 Renderer build） |
| `.venv\Scripts\python.exe -m ruff check src tests` | PASS |
| `.venv\Scripts\python.exe -m compileall -q src tests` | PASS |
| `git diff --check` | PASS；仅 CRLF 转换提示，无 whitespace error |
| Workspace layout full | FAIL：既有顶层 `D:\study\NetConsole-Workspace\docs` |
| Workspace layout repo-only | FAIL：同一既有顶层 `docs` |

新增/直接受影响的定向测试：

- `meshHttpTrace.test.ts`：请求参数、request id、SQL ranges、payload、Abort 和非 MESH 路径。
- `MeshMetricChart.test.ts`：mount/init/dispose/unmount 计数平衡。
- `meshRawSampleCache.test.ts`：coverage stats 输出。
- `test_mesh_raw_sample_query.py`：raw SQL range purpose/count。

上述单测和全量 MESH 集合均未删除断言或降低断言；3 个 warning 来自既有 Starlette/httpx 和 HTTP 422 弃用，不是失败。
