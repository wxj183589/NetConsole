# Dual package acceptance

| Item | Result | Evidence |
| --- | --- | --- |
| Full installer | PASS | NSIS extraction, release manifest hash/size, package smoke |
| Portable ZIP | PASS | 7-Zip test, portable.mode marker, same `afd1b4fc` source |
| Full feature profile | PASS | `ELECTRON_FEATURE_PROFILE=full` |
| Customer/Custom/Lite reintroduction | PASS | `CUSTOM_EDITION_RETIRED=YES`; no customer build requested |
| Backend/frontend/source commit equality | PASS | all equal `afd1b4fc35f2ac2e2ae8d3a52e783ea7b0ac630c` |
| Local GUI manual acceptance | NOT AVAILABLE | automated startup/smoke only |
| Real Windows install | PENDING | no manual installer environment in this run |
| Field acceptance | NOT_AVAILABLE | no real device/site acceptance requested or available |

结论：双制品可作为同一 main commit 的自动化验收候选，不能升级为人工 GUI、真实安装或现场验收通过。
