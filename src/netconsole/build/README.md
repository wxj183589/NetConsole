# Python 构建辅助

本目录提供 PyInstaller 构建锁、输出路径和制品安全校验，区分源码、构建临时目录与最终交付目录。它不属于运行时业务包，也不保存构建产物。

主要入口为 `clean_build_lock.py`；构建过程由 `scripts/build` 调用。修改规则后运行构建/制品清单测试，并清理 `dist`、build 临时输出。
