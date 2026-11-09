# 回归验证

测试环境含并行未提交工作树修改，不能作为最终提交对应源码的集成 Gate。

- Python：`tests/test_mesh_*.py` 与 `tests/test_rebuild_mesh_parsed_data.py`，432 passed，3 条弃用警告。
- Renderer：MESH 组件和 MeshAnalysisView 定向测试 24 files / 230 tests passed。
- Electron：`tests/ipc.test.ts`、`tests/security.test.ts`，48 passed；诊断、workload、workspace 和 preload 五个测试文件 26 passed。
- Export Process：`tests/test_export_process_framework.py -k mesh`，1 passed、14 deselected；不代表全消费者覆盖。
- Renderer `pnpm run build`（含 `vue-tsc -b`）通过，Vite 报告既有大 chunk 警告。
- `python -m scripts.check_workspace_layout`、Storage Registry 检查、四个 MESH 文件的定向 Ruff、`git diff --check` 通过。

完整 Electron MESH、Export 消费者、全范围 Ruff、py_compile、文档布局和最终提交对应源码的完整集成 Gate 尚未完成。本轮其他定向测试与上述 Python 集合重叠，不重复累计。
