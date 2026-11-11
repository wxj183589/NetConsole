# Full installer build

- `INSTALLER=PASS`
- Edition：`full`
- Full feature profile：`full`
- `ADMIN_UNLOCK_CONFIGURED=false`
- Source/backend/frontend commit：`afd1b4fc35f2ac2e2ae8d3a52e783ea7b0ac630c`
- `PACKAGED_DIRTY=false`
- Package smoke：`PASS`
- Real Windows install：`PENDING`

制品：

`D:\study\NetConsole-Workspace\release\v1.5.13\build-20261111-0735-afd1b4fc\NetConsole-Full-1.5.13.0-afd1b4fc-x64-setup.exe`

- Size：`158267994` bytes
- SHA-256：`cdd345c38220f596b00f564ac1016fae172c21350263df76d651d196bc02af66`
- Release manifest：同目录 `NetConsole-Full-1.5.13.0-afd1b4fc-x64-setup.exe.release.json`
- NSIS archive extraction：7-Zip `Everything is Ok`

构建期间完成 Web 1542 tests、Electron 314 tests、PyInstaller 依赖/资源校验、版本一致性与包内 smoke。Vite large-chunk 仅为 warning，不影响构建成功。
