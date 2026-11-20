# NetConsole v1.5.17 最终交接

## 状态

`PARTIAL`：代码复审、版本更新、定向测试和本地双包/ZIP 已完成；正式发布前仍需 upstream 对齐和真实环境验收。

## 交付证据

- 产品 Commit：`d687ba575b27fdbc11a2013b9afc467c1bb4d07c`
- Release 目录：`D:\study\NetConsole-Workspace\release\v1.5.17\build-0-d687ba57`
- Installer SHA-256：`2c17fb1c0b0c36e80f78ccf2db7602f986d441c4228933eb51d184b74cc540c1`
- Portable SHA-256：`575cebf6f5f6544b64af6dbd058643f2c5c183d41272d635a167529ed8a6650c`
- Full Distribution ZIP：`D:\study\NetConsole-Workspace\release\v1.5.17\NetConsole-v1.5.17-Full-Distribution.zip`；SHA-256 `88471377c42740ec2d65633104b05cc8b4abaf39ce988b6fbaf5195f3e87ab9a`。
- Package smoke：PASS；Full test suite：NOT RUN；Full L3/Architecture Gate：NOT RUN。

## 数据安全

`PRODUCTION_DATA_MODIFIED=0`；`DEV_REAL_DATA_MODIFIED=0`；`DATABASES_REMOVED=0`；`REAL_DEVICES_ACCESSED=0`；原始 RAR 未修改。一次误启动的生命周期审计在缺少 devices.db 后立即失败，未写入真实数据；脚本已改为显式 data-root。

## 下一步

1. 在获授权后 Push 当前分支并从最终 upstream HEAD 使用 canonical `package_windows.ps1 -Edition full` 重建正式包。
2. 在隔离 Windows 环境完成 Installer/Portable GUI 启动、退出、升级/卸载和数据根验收。
3. 在真实设备与 Windows 10 20H2 环境补齐六项 PARTIAL，不改写历史结论。
