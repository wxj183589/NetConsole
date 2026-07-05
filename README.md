# NetConsole

NetConsole 是一个 Windows 本地桌面网络运维工具，当前实现为 PySide6 / Qt 应用，使用 SQLite 和站点目录保存本地数据。项目主要覆盖设备管理、配置采集、文件管理、AC / FIT-AP 管理、轨道交通无线网络分析、车载 MR 采集分析和网络小工具。

开发、维护和后续 Codex 任务请先阅读：

- [文档入口](docs/README.md)
- [开发约定](docs/DEVELOPMENT_CONVENTIONS.md)
- [Codex 工作流](docs/CODEX_WORKFLOW.md)
- [构建与发布](docs/BUILD_AND_RELEASE.md)
- [第三方依赖说明](docs/THIRD_PARTY_DEPENDENCIES.md)

## 开发环境启动

以下命令是开发环境示例，不是硬编码路径要求：

```powershell
.\.venv\Scripts\python.exe .\main.py
```

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 数据目录

开发环境和便携发布版本默认在应用根或指定数据根下创建本地数据目录：

```text
data/
  sites/
    <site_name>/
      site_meta.json
      db/
      files/
      cache/
runtime/
  logs/
```

详细规则见 [数据目录规范](docs/DATA_LAYOUT.md)。

## 发布

构建入口：

```powershell
.\build_release.bat
.\build_nuitka_release.bat
```

发布包规则、白名单和禁入目录见 [构建与发布](docs/BUILD_AND_RELEASE.md)。

发布包需要保留 `_internal`、`data`、`runtime` 目录，以及 PySide6、网络工具和 VC++ 运行库等运行依赖。

## 许可证与第三方依赖

NetConsole 当前按非商业 GPLv3 项目分发。界面美化使用 `PySide6-Fluent-Widgets==1.11.2`，即 QFluentWidgets 免费版；商业用途需要购买 QFluentWidgets 商业授权。不要混装 PyQt / PyQt6 / PySide2 版本的 Fluent Widgets，详见 [第三方依赖说明](docs/THIRD_PARTY_DEPENDENCIES.md)。
