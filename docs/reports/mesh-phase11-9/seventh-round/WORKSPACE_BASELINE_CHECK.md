# Workspace 基线检查

## 实际检查

执行：

```text
.venv\Scripts\python.exe -m scripts.check_workspace_layout
.venv\Scripts\python.exe -m scripts.check_workspace_layout --repo-only
```

两次均返回 `WORKSPACE_LAYOUT_CHECK=FAIL`，唯一报告项为：

```text
KIND: UNAPPROVED_WORKSPACE_TOP_LEVEL
PATH: D:\study\NetConsole-Workspace\docs
RULE: Workspace 顶层只能使用标准目录或登记的历史例外
```

该目录在本轮开始前已存在，第六轮报告已记录同一个 blocker；本轮没有创建、移动、删除或修改它。当前目录 creation time 为 `2026-11-10T08:51:33.2314801+08:00`，本轮 MESH 报告全部位于仓库内的 `NetConsole\docs\reports\mesh-phase11-9\`，没有新增 Workspace 顶层目录。

## 分类

`BASELINE_WORKSPACE_BLOCKER`

它与 MESH 查询、缓存、真实 Electron 运行无关，不修改全局规则、不删除顶层 docs、不移动其他项目文档。作为 Workspace 总 Gate 的既有失败保留；不能把它改写成 MESH 功能 PASS，也不能用它否定已通过的 MESH 核心数据证据。
