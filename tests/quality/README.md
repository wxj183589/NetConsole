# 质量检查测试

本目录验证仓库质量门禁的排除规则、稳定输出、非零失败和当前 README 覆盖。测试使用临时路径模拟 Git 跟踪列表，不读取真实设备或写入项目运行数据。

`test_directory_readmes.py` 验证目录职责覆盖；`test_change_impact.py` 验证 L1-L4 判级、稳定消费者 ID、Registry 证据、关键路径和 GitHub 输出；`test_local_gate.py` 验证主线基线解析、AUTO 风险路由、suite fail-closed、子进程失败、DataRoot 隔离、Windows 只读文件清理、报告输出和 12 入口 Main Smoke。使用项目虚拟环境运行 `python -m pytest tests/quality -q`。修改检查器的分类或输出时同步更新这些测试并运行 `git diff --check`。
