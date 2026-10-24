; NetConsole business data must never share the application installation tree.
; This file is included by electron-builder's existing assisted NSIS installer.

!include "LogicLib.nsh"
!include "nsDialogs.nsh"
!include "${__FILEDIR__}\..\dist\installer-build\installer-build-identity.nsh"

!macro customHeader
  VIAddVersionKey /LANG=1033 "InstallerGitCommit" "${NETCONSOLE_INSTALLER_GIT_COMMIT}"
  VIAddVersionKey /LANG=1033 "InstallerGitShort" "${NETCONSOLE_INSTALLER_GIT_SHORT}"
  VIAddVersionKey /LANG=1033 "InstallerBuildTime" "${NETCONSOLE_INSTALLER_BUILD_TIME}"
  VIAddVersionKey /LANG=1033 "InstallerBuildId" "${NETCONSOLE_INSTALLER_BUILD_ID}"
  VIAddVersionKey /LANG=1033 "InstallerEdition" "${NETCONSOLE_INSTALLER_EDITION}"
  VIAddVersionKey /LANG=1033 "InstallerFeatureProfile" "${NETCONSOLE_INSTALLER_FEATURE_PROFILE}"
  VIAddVersionKey /LANG=1033 "InstallerPolicy" "${NETCONSOLE_INSTALLER_POLICY}"
  VIAddVersionKey /LANG=1033 "InstallerPolicySHA256" "${NETCONSOLE_INSTALLER_POLICY_SHA256}"
!macroend

Var NetConsoleExistingDataRoot
Var NetConsoleExistingDataRoot64
Var NetConsoleExistingDataRoot32
!ifndef BUILD_UNINSTALLER
Var NetConsoleDataRoot
Var NetConsoleRegistryViewConflict
!endif
Var NetConsoleDataRootPointerResult
!ifndef BUILD_UNINSTALLER
Var NetConsoleInstallerLogPath
Var NetConsoleInstallerLogHandle
Var NetConsoleInstallerDiagnosticMessage
Var NetConsoleInstallerDiagnosticId
Var NetConsoleBackendDiagnosticLogPath
!endif

!ifndef BUILD_UNINSTALLER
Function NetConsoleInstallerWriteDiagnostic
  ${If} $NetConsoleInstallerLogHandle != ""
    FileWrite $NetConsoleInstallerLogHandle "$NetConsoleInstallerDiagnosticMessage$\r$\n"
  ${EndIf}
  DetailPrint "$NetConsoleInstallerDiagnosticMessage"
FunctionEnd

Function NetConsoleInstallerAbort
  Call NetConsoleInstallerWriteDiagnostic
  ${If} $NetConsoleInstallerLogHandle != ""
    FileClose $NetConsoleInstallerLogHandle
    StrCpy $NetConsoleInstallerLogHandle ""
  ${EndIf}
  MessageBox MB_ICONSTOP "$NetConsoleInstallerDiagnosticMessage$\r$\n$\r$\n诊断日志：$NetConsoleInstallerLogPath"
  Abort
FunctionEnd

Function NetConsoleInstallerInitDiagnostic
  System::Call 'kernel32::GetCurrentProcessId()i.r0'
  System::Call 'kernel32::GetTickCount()i.r1'
  StrCpy $NetConsoleInstallerDiagnosticId "$0-$1"
  StrCpy $NetConsoleInstallerLogPath "$TEMP\NetConsole-Installer-$NetConsoleInstallerDiagnosticId.log"
  StrCpy $NetConsoleBackendDiagnosticLogPath "$TEMP\NetConsole-Backend-$NetConsoleInstallerDiagnosticId.jsonl"
  ClearErrors
  FileOpen $NetConsoleInstallerLogHandle "$NetConsoleInstallerLogPath" a
  IfErrors NetConsoleInstallerDiagnosticUnavailable
  StrCpy $NetConsoleInstallerDiagnosticMessage "stage=customInit diagnostic_id=$NetConsoleInstallerDiagnosticId registry=not-written installer_log=$NetConsoleInstallerLogPath backend_diagnostic_log=$NetConsoleBackendDiagnosticLogPath"
  Call NetConsoleInstallerWriteDiagnostic
  Return
  NetConsoleInstallerDiagnosticUnavailable:
  StrCpy $NetConsoleInstallerLogHandle ""
  DetailPrint "安装器诊断日志无法写入：$NetConsoleInstallerLogPath"
FunctionEnd

Function NetConsoleReadDataRootViews
  StrCpy $NetConsoleExistingDataRoot64 ""
  StrCpy $NetConsoleExistingDataRoot32 ""
  StrCpy $NetConsoleExistingDataRoot ""
  StrCpy $NetConsoleRegistryViewConflict "0"
  SetRegView 64
  ReadRegStr $NetConsoleExistingDataRoot64 HKLM "Software\NetConsole" "DataRoot"
  SetRegView 32
  ReadRegStr $NetConsoleExistingDataRoot32 HKLM "Software\NetConsole" "DataRoot"
  ${If} $NetConsoleExistingDataRoot64 != ""
  ${AndIf} $NetConsoleExistingDataRoot32 != ""
    StrCmp "$NetConsoleExistingDataRoot64" "$NetConsoleExistingDataRoot32" NetConsoleRegistryViewsSame NetConsoleRegistryViewsConflict
  ${EndIf}
  Goto NetConsoleRegistryViewsSelect

  NetConsoleRegistryViewsSame:
  Goto NetConsoleRegistryViewsSelect

  NetConsoleRegistryViewsConflict:
  StrCpy $NetConsoleRegistryViewConflict "1"

  NetConsoleRegistryViewsSelect:
  ${If} $NetConsoleExistingDataRoot64 != ""
    StrCpy $NetConsoleExistingDataRoot "$NetConsoleExistingDataRoot64"
  ${Else}
    StrCpy $NetConsoleExistingDataRoot "$NetConsoleExistingDataRoot32"
  ${EndIf}
  SetRegView 64
FunctionEnd

Function NetConsoleRestoreDataRootPointer
  SetRegView 64
  ${If} $NetConsoleExistingDataRoot64 != ""
    WriteRegStr HKLM "Software\NetConsole" "DataRoot" "$NetConsoleExistingDataRoot64"
  ${Else}
    DeleteRegValue HKLM "Software\NetConsole" "DataRoot"
  ${EndIf}
  SetRegView 32
  ${If} $NetConsoleExistingDataRoot32 != ""
    WriteRegStr HKLM "Software\NetConsole" "DataRoot" "$NetConsoleExistingDataRoot32"
  ${Else}
    DeleteRegValue HKLM "Software\NetConsole" "DataRoot"
  ${EndIf}
  SetRegView 64
FunctionEnd

Function NetConsolePublishDataRootPointer
  StrCpy $NetConsoleDataRootPointerResult "ok"
  SetRegView 64
  ClearErrors
  WriteRegStr HKLM "Software\NetConsole" "DataRoot" "$NetConsoleDataRoot"
  IfErrors NetConsolePublishDataRootPointerFailed
  SetRegView 32
  ClearErrors
  WriteRegStr HKLM "Software\NetConsole" "DataRoot" "$NetConsoleDataRoot"
  IfErrors NetConsolePublishDataRootPointerFailed

  SetRegView 64
  ReadRegStr $0 HKLM "Software\NetConsole" "DataRoot"
  StrCmp "$0" "$NetConsoleDataRoot" 0 NetConsolePublishDataRootPointerFailedReadback
  SetRegView 32
  ReadRegStr $0 HKLM "Software\NetConsole" "DataRoot"
  StrCmp "$0" "$NetConsoleDataRoot" 0 NetConsolePublishDataRootPointerFailedReadback
  SetRegView 64
  Return

  NetConsolePublishDataRootPointerFailedReadback:
  StrCpy $NetConsoleDataRootPointerResult "Registry DataRoot 回读与安装器选择不一致"
  Call NetConsoleRestoreDataRootPointer
  Return

  NetConsolePublishDataRootPointerFailed:
  StrCpy $NetConsoleDataRootPointerResult "Registry DataRoot 写入失败"
  Call NetConsoleRestoreDataRootPointer
FunctionEnd
!endif

!ifdef BUILD_UNINSTALLER
; electron-builder expands customUnInit/customUnInstall inside the NSIS
; uninstaller section.  NSIS requires calls from that section to target an
; un.* function, so keep the same narrow registry-only logic in that namespace.
Function un.NetConsoleReadDataRootViews
  StrCpy $NetConsoleExistingDataRoot64 ""
  StrCpy $NetConsoleExistingDataRoot32 ""
  StrCpy $NetConsoleExistingDataRoot ""
  SetRegView 64
  ReadRegStr $NetConsoleExistingDataRoot64 HKLM "Software\NetConsole" "DataRoot"
  SetRegView 32
  ReadRegStr $NetConsoleExistingDataRoot32 HKLM "Software\NetConsole" "DataRoot"
  Goto un.NetConsoleRegistryViewsSelect

  un.NetConsoleRegistryViewsSelect:
  ${If} $NetConsoleExistingDataRoot64 != ""
    StrCpy $NetConsoleExistingDataRoot "$NetConsoleExistingDataRoot64"
  ${Else}
    StrCpy $NetConsoleExistingDataRoot "$NetConsoleExistingDataRoot32"
  ${EndIf}
  SetRegView 64
FunctionEnd

Function un.NetConsoleClearDataRootPointers
  StrCpy $NetConsoleDataRootPointerResult "ok"
  SetRegView 64
  ${If} $NetConsoleExistingDataRoot64 != ""
    ClearErrors
    DeleteRegValue HKLM "Software\NetConsole" "DataRoot"
    IfErrors un.NetConsoleClearDataRootPointersFailed
  ${EndIf}
  SetRegView 32
  ${If} $NetConsoleExistingDataRoot32 != ""
    ClearErrors
    DeleteRegValue HKLM "Software\NetConsole" "DataRoot"
    IfErrors un.NetConsoleClearDataRootPointersFailed
  ${EndIf}
  Call un.NetConsoleReadDataRootViews
  ${If} $NetConsoleExistingDataRoot64 != ""
  ${OrIf} $NetConsoleExistingDataRoot32 != ""
    Goto un.NetConsoleClearDataRootPointersFailed
  ${EndIf}
  SetRegView 64
  Return

  un.NetConsoleClearDataRootPointersFailed:
  StrCpy $NetConsoleDataRootPointerResult "清洁卸载未能清除 NetConsole DataRoot 指针"
  SetRegView 64
FunctionEnd
!endif

!macro customUnInit
  SetRegView 64
  Call un.NetConsoleReadDataRootViews
  StrCpy $NetConsoleDataRootPointerResult "NORMAL_UNINSTALL"
  ; electron-builder invokes the old uninstaller with /S /KEEP_APP_DATA and
  ; --updated during upgrade/repair. Silent lifecycle is always normal and
  ; never presents a clean-uninstall choice.
  IfSilent NetConsoleUninstallSilent
  MessageBox MB_ICONQUESTION|MB_YESNO|MB_DEFBUTTON1 "请选择卸载方式：$\r$\n$\r$\n是：普通卸载（默认），保留业务数据和 DataRoot 指针。$\r$\n否：继续选择清洁卸载。" IDYES NetConsoleUninstallNormal
  MessageBox MB_ICONEXCLAMATION|MB_YESNO|MB_DEFBUTTON2 "清洁卸载将清除 NetConsole 自有的机器级 DataRoot 指针，但不会删除业务数据、数据库、日志、备份或任何其他应用数据。$\r$\n$\r$\n历史数据目录：$NetConsoleExistingDataRoot$\r$\n请确认已记录该路径。是否继续？" IDYES NetConsoleUninstallClean
  Abort

  NetConsoleUninstallNormal:
  StrCpy $NetConsoleDataRootPointerResult "NORMAL_UNINSTALL"
  Return

  NetConsoleUninstallClean:
  StrCpy $NetConsoleDataRootPointerResult "CLEAN_UNINSTALL"
  Return

  NetConsoleUninstallSilent:
  DetailPrint "自动升级/修复：NORMAL_UNINSTALL，保留业务数据和 DataRoot 指针。"
!macroend

!macro customUnInstall
  ${If} $NetConsoleDataRootPointerResult == "CLEAN_UNINSTALL"
    Call un.NetConsoleClearDataRootPointers
    ${If} $NetConsoleDataRootPointerResult != "ok"
      MessageBox MB_ICONSTOP "$NetConsoleDataRootPointerResult。业务数据未删除；请以管理员身份重试。"
      Abort
    ${EndIf}
    DetailPrint "CLEAN_UNINSTALL：仅清除 NetConsole DataRoot 指针；业务数据保留。"
  ${Else}
    DetailPrint "NORMAL_UNINSTALL：保留 NetConsole DataRoot 指针和业务数据。"
  ${EndIf}
!macroend

!ifndef BUILD_UNINSTALLER
Var NetConsoleDataRootChanged
Var NetConsoleDataRootInput
Var NetConsoleDataRootStatus
Var NetConsoleDataRootProbeSource
Var NetConsoleDataRootProbeTarget
Var NetConsoleDataRootProbeExpected
Var NetConsoleDataRootProbeActual
Var NetConsoleDataRootProbeResult
Var NetConsoleDataRootProbeErrorCode
Var NetConsoleDataRootProbeErrorSource
Var NetConsoleDataRootProbePid
Var NetConsoleDataRootProbeTick
Var NetConsoleDataRootFindHandle
Var NetConsoleDataRootFindName
Var NetConsoleDataRootHasEntries
Var NetConsoleDataRootNormalized
Var NetConsoleDataRootDriveRoot
Var NetConsoleDataRootDriveType
Var NetConsoleDataRootExists
Var NetConsoleDataRootBusinessData
Var NetConsoleDataRootPathsMatch
Var NetConsoleDataRootExistingNormalized
Var NetConsoleDataRootSelectedNormalized
Var NetConsolePerformanceMode
Var NetConsoleInstallMode
Var NetConsoleInstallModeReuseRadio
Var NetConsoleInstallModeFreshRadio
Var NetConsoleInstallModeMigrateRadio
Var NetConsoleInstallModePageMode
Var NetConsoleInstallModeHistoryLabel
Var NetConsoleInstallModeDescriptionLabel
Var NetConsoleDataRootPageModeLabel
Var NetConsoleDataRootPageSourceLabel
Var NetConsoleDataRootBrowseButton
Var NetConsoleEnvironmentDataRoot
!endif

!ifndef BUILD_UNINSTALLER
!macro customInit
  Call NetConsoleInstallerInitDiagnostic
  DetailPrint "Installer identity: app=${NETCONSOLE_INSTALLER_APP_VERSION} commit=${NETCONSOLE_INSTALLER_GIT_COMMIT} build_time=${NETCONSOLE_INSTALLER_BUILD_TIME} build_id=${NETCONSOLE_INSTALLER_BUILD_ID} policy=${NETCONSOLE_INSTALLER_POLICY}"
  InitPluginsDir
  File /oname=$PLUGINSDIR\netconsole-installer-build.json "${NETCONSOLE_INSTALLER_MANIFEST_PATH}"
  File /oname=$PLUGINSDIR\netconsole-installer-data-root.nsh "${NETCONSOLE_INSTALLER_POLICY_SOURCE_PATH}"
  Call NetConsoleReadDataRootViews
  ${If} $NetConsoleRegistryViewConflict == "1"
    StrCpy $NetConsoleInstallerDiagnosticMessage "stage=registry-read result=32-64-view-conflict registry=preserved"
    Call NetConsoleInstallerAbort
  ${EndIf}
  ReadEnvStr $NetConsoleEnvironmentDataRoot "NETCONSOLE_DATA_ROOT"
  ${If} $NetConsoleExistingDataRoot != ""
    StrCpy $NetConsoleDataRoot "$NetConsoleExistingDataRoot"
    StrCpy $NetConsoleInstallMode "REUSE_EXISTING_DATA"
  ${Else}
    StrCpy $NetConsoleInstallMode "FRESH_CLEAN_INSTALL"
    Call NetConsoleSelectDefaultDataRoot
  ${EndIf}
  StrCpy $NetConsoleInstallerDiagnosticMessage "stage=installer-mode-selected mode=$NetConsoleInstallMode data_root=$NetConsoleDataRoot diagnostic_id=$NetConsoleInstallerDiagnosticId registry=not-written"
  Call NetConsoleInstallerWriteDiagnostic
  StrCpy $NetConsoleDataRootChanged "0"
  StrCpy $NetConsolePerformanceMode "standard"
!macroend

!macro customPageAfterChangeDir
  Page custom NetConsoleInstallModePageCreate NetConsoleInstallModePageLeave
  Page custom NetConsoleDataRootPageCreate NetConsoleDataRootPageLeave
!macroend

Function NetConsoleSelectDefaultDataRoot
  StrCpy $NetConsoleDataRoot ""
  ReadEnvStr $5 "SystemDrive"
  ${If} $5 == ""
    StrCpy $5 "C:"
  ${EndIf}
  StrCpy $5 "$5" 2
  ; Prefer D: only when it is really present and fixed. Otherwise enumerate
  ; actual logical drives and never fabricate a missing drive path.
  StrCpy $0 "D:\"
  System::Call 'kernel32::GetDriveTypeW(w r0)i.r1'
  ${If} $1 == 3
    StrCpy $NetConsoleDataRoot "D:\NetConsoleData"
    Return
  ${EndIf}
  System::Call 'kernel32::GetLogicalDriveStringsW(i ${NSIS_MAX_STRLEN}, w .r0)i.r1'
  StrCpy $2 "0"
  NetConsoleSelectDefaultDataRootLoop:
  StrCpy $3 "$0" 3 $2
  StrCmp $3 "" NetConsoleSelectDefaultDataRootDone
  System::Call 'kernel32::GetDriveTypeW(w r3)i.r4'
  StrCmp $4 3 0 NetConsoleSelectDefaultDataRootNext
  StrCpy $6 "$3" 2
  StrCmp "$6" "$5" NetConsoleSelectDefaultDataRootNext
  StrCpy $NetConsoleDataRoot "$3NetConsoleData"
  Return
  NetConsoleSelectDefaultDataRootNext:
  IntOp $2 $2 + 4
  Goto NetConsoleSelectDefaultDataRootLoop
  NetConsoleSelectDefaultDataRootDone:
FunctionEnd

Function NetConsoleInstallModePageCreate
  ${If} $NetConsoleExistingDataRoot == ""
    Abort
  ${EndIf}
  StrCpy $NetConsoleInstallModePageMode "$NetConsoleInstallMode"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 20u "请选择安装方式。原数据目录不会因选择全新安装而被删除。"
  Pop $0
  ${NSD_CreateLabel} 0 24u 100% 30u ""
  Pop $NetConsoleInstallModeHistoryLabel
  ${NSD_CreateLabel} 0 58u 100% 12u "安装方式："
  Pop $0
  ${NSD_CreateRadioButton} 0 74u 100% 18u "沿用已有数据（推荐）"
  Pop $NetConsoleInstallModeReuseRadio
  ${NSD_OnClick} $NetConsoleInstallModeReuseRadio NetConsoleInstallModeReuseClicked
  ${NSD_CreateRadioButton} 0 96u 100% 18u "全新安装"
  Pop $NetConsoleInstallModeFreshRadio
  ${NSD_OnClick} $NetConsoleInstallModeFreshRadio NetConsoleInstallModeFreshClicked
  ${NSD_CreateRadioButton} 0 118u 100% 18u "迁移已有数据（高级）"
  Pop $NetConsoleInstallModeMigrateRadio
  ${NSD_OnClick} $NetConsoleInstallModeMigrateRadio NetConsoleInstallModeMigrateClicked
  ${NSD_CreateLabel} 0 142u 100% 30u ""
  Pop $NetConsoleInstallModeDescriptionLabel
  Call NetConsoleRefreshInstallModeHistory
  Call NetConsoleRefreshInstallModeDescription
  ${If} $NetConsoleInstallModePageMode == "FRESH_CLEAN_INSTALL"
    ${NSD_Check} $NetConsoleInstallModeFreshRadio
  ${ElseIf} $NetConsoleInstallModePageMode == "MIGRATE_EXISTING_DATA"
    ${NSD_Check} $NetConsoleInstallModeMigrateRadio
  ${Else}
    ${NSD_Check} $NetConsoleInstallModeReuseRadio
  ${EndIf}
  nsDialogs::Show
FunctionEnd

Function NetConsoleInstallModePageLeave
  StrCpy $1 "$NetConsoleInstallModePageMode"
  ${NSD_GetState} $NetConsoleInstallModeReuseRadio $0
  ${If} $0 == 1
    StrCpy $NetConsoleInstallMode "REUSE_EXISTING_DATA"
  ${Else}
    ${NSD_GetState} $NetConsoleInstallModeFreshRadio $0
    ${If} $0 == 1
      StrCpy $NetConsoleInstallMode "FRESH_CLEAN_INSTALL"
    ${Else}
      StrCpy $NetConsoleInstallMode "MIGRATE_EXISTING_DATA"
    ${EndIf}
  ${EndIf}
  ${If} $NetConsoleInstallMode == "REUSE_EXISTING_DATA"
    StrCpy $NetConsoleDataRoot "$NetConsoleExistingDataRoot"
  ${ElseIf} $NetConsoleInstallMode == "FRESH_CLEAN_INSTALL"
    ${If} $1 != "FRESH_CLEAN_INSTALL"
      StrCpy $NetConsoleDataRoot ""
    ${EndIf}
  ${ElseIf} $1 == "REUSE_EXISTING_DATA"
    StrCpy $NetConsoleDataRoot ""
  ${EndIf}
FunctionEnd

Function NetConsoleRefreshInstallModeHistory
  IfFileExists "$NetConsoleExistingDataRoot\." NetConsoleInstallModeHistoryAvailable NetConsoleInstallModeHistoryMissing
NetConsoleInstallModeHistoryAvailable:
  ${NSD_SetText} $NetConsoleInstallModeHistoryLabel "历史数据目录：$NetConsoleExistingDataRoot"
  Return
NetConsoleInstallModeHistoryMissing:
  ${NSD_SetText} $NetConsoleInstallModeHistoryLabel "历史数据目录：$NetConsoleExistingDataRoot$\r$\n状态：历史数据目录不可访问"
FunctionEnd

Function NetConsoleRefreshInstallModeDescription
  ${If} $NetConsoleInstallModePageMode == "FRESH_CLEAN_INSTALL"
    ${NSD_SetText} $NetConsoleInstallModeDescriptionLabel "模式说明：创建独立的新数据环境，原来的数据库和文件不会删除。"
  ${ElseIf} $NetConsoleInstallModePageMode == "MIGRATE_EXISTING_DATA"
    ${NSD_SetText} $NetConsoleInstallModeDescriptionLabel "模式说明：将已有数据安全迁移至新位置，旧目录保留。"
  ${Else}
    ${NSD_SetText} $NetConsoleInstallModeDescriptionLabel "模式说明：使用原来的局点和历史记录，安装时验证数据完整性。"
  ${EndIf}
FunctionEnd

Function NetConsoleInstallModeReuseClicked
  StrCpy $NetConsoleInstallModePageMode "REUSE_EXISTING_DATA"
  Call NetConsoleRefreshInstallModeDescription
FunctionEnd

Function NetConsoleInstallModeFreshClicked
  StrCpy $NetConsoleInstallModePageMode "FRESH_CLEAN_INSTALL"
  Call NetConsoleRefreshInstallModeDescription
FunctionEnd

Function NetConsoleInstallModeMigrateClicked
  StrCpy $NetConsoleInstallModePageMode "MIGRATE_EXISTING_DATA"
  Call NetConsoleRefreshInstallModeDescription
FunctionEnd

Function NetConsoleDataRootCheckBusinessData
  StrCpy $NetConsoleDataRootBusinessData "0"
  IfFileExists "$NetConsoleDataRoot\config\." NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\sites\." NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\runtime\." NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\agents\." NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\migrations\." NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\staging\." NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\backups\." NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\data\." NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\runtime_mode.json" NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\application.json" NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\app.json" NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\bootstrap.json" NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\devices.db" NetConsoleDataRootBusinessDataFound
  IfFileExists "$NetConsoleDataRoot\site_registry.json" NetConsoleDataRootBusinessDataFound
  Return
  NetConsoleDataRootBusinessDataFound:
  StrCpy $NetConsoleDataRootBusinessData "1"
FunctionEnd

Function NetConsoleDataRootPathsMatch
  StrCpy $NetConsoleDataRootPathsMatch "0"
  StrCpy $0 "$NetConsoleExistingDataRoot"
  System::Call 'kernel32::GetFullPathNameW(w r0, i ${NSIS_MAX_STRLEN}, w .r1, p 0)i.r2'
  StrCmp $2 0 NetConsoleDataRootPathsMatchDone
  StrCpy $NetConsoleDataRootExistingNormalized "$1"
  StrCpy $0 "$NetConsoleDataRoot"
  System::Call 'kernel32::GetFullPathNameW(w r0, i ${NSIS_MAX_STRLEN}, w .r1, p 0)i.r2'
  StrCmp $2 0 NetConsoleDataRootPathsMatchDone
  StrCpy $NetConsoleDataRootSelectedNormalized "$1"
  StrCmp "$NetConsoleDataRootExistingNormalized" "$NetConsoleDataRootSelectedNormalized" 0 NetConsoleDataRootPathsMatchDone
  StrCpy $NetConsoleDataRootPathsMatch "1"
  NetConsoleDataRootPathsMatchDone:
FunctionEnd

!macro customInstall
  StrCpy $NetConsoleInstallerDiagnosticMessage "stage=data-root-location-validation path=$NetConsoleDataRoot registry=not-written"
  Call NetConsoleInstallerWriteDiagnostic
  Call NetConsoleValidateDataRootLocation
  ${If} $NetConsoleDataRootProbeResult != "ok"
    StrCpy $NetConsoleInstallerDiagnosticMessage "stage=data-root-location-validation result=$NetConsoleDataRootProbeResult error_source=$NetConsoleDataRootProbeErrorSource error_code=$NetConsoleDataRootProbeErrorCode registry=not-written"
    Call NetConsoleInstallerAbort
  ${EndIf}
  ${If} $NetConsoleInstallMode == "REUSE_EXISTING_DATA"
    ${If} $NetConsoleDataRootExists != "1"
      StrCpy $NetConsoleInstallerDiagnosticMessage "stage=existing-root-check result=unavailable registry=not-written"
      Call NetConsoleInstallerAbort
    ${EndIf}
  ${EndIf}
  ${If} $NetConsoleEnvironmentDataRoot != ""
    StrCmp "$NetConsoleEnvironmentDataRoot" "$NetConsoleDataRoot" +2 0
      StrCpy $NetConsoleInstallerDiagnosticMessage "stage=environment-root-check result=mismatch registry=not-written"
      Call NetConsoleInstallerAbort
  ${EndIf}

  ; A relocation is never a pointer-only update.  The packaged helper stages,
  ; verifies SQLite files and publishes the new root before this registry value
  ; changes.  This branch is reachable only after the user explicitly chose
  ; MIGRATE_EXISTING_DATA; selecting a different path alone is not enough.
  ${If} $NetConsoleInstallMode == "MIGRATE_EXISTING_DATA"
    IfFileExists "$NetConsoleExistingDataRoot\." +2 0
      StrCpy $NetConsoleInstallerDiagnosticMessage "stage=data-root-migration result=source-unavailable registry=not-written"
      Call NetConsoleInstallerAbort
    DetailPrint "正在迁移现有 NetConsole 数据；旧数据将保留为只读备份。"
    ExecWait '"$INSTDIR\resources\backend\NetConsoleBackend.exe" --migrate-data-root --source "$NetConsoleExistingDataRoot" --target "$NetConsoleDataRoot" --installation-root "$INSTDIR"' $0
    StrCpy $NetConsoleInstallerDiagnosticMessage "stage=data-root-migration exit_code=$0 registry=not-written"
    Call NetConsoleInstallerWriteDiagnostic
    ${If} $0 != 0
      StrCpy $NetConsoleInstallerDiagnosticMessage "stage=data-root-migration result=failed exit_code=$0 registry=not-written old-data=preserved"
      Call NetConsoleInstallerAbort
    ${EndIf}
  ${EndIf}
  Call NetConsoleRunDataRootProbe
  ${If} $NetConsoleDataRootProbeResult != "ok"
    DetailPrint "DataRoot probe failed: step=$NetConsoleDataRootProbeResult error_source=$NetConsoleDataRootProbeErrorSource error_code=$NetConsoleDataRootProbeErrorCode"
    StrCpy $NetConsoleInstallerDiagnosticMessage "stage=data-root-probe result=$NetConsoleDataRootProbeResult error_source=$NetConsoleDataRootProbeErrorSource error_code=$NetConsoleDataRootProbeErrorCode registry=not-written"
    Call NetConsoleInstallerAbort
  ${EndIf}
  ${If} $NetConsoleInstallMode == "FRESH_CLEAN_INSTALL"
    Call NetConsoleDataRootCheckBusinessData
    ${If} $NetConsoleDataRootBusinessData == "1"
      StrCpy $NetConsoleInstallerDiagnosticMessage "stage=clean-install-business-data-check result=conflict registry=not-written"
      Call NetConsoleInstallerAbort
    ${EndIf}
  ${EndIf}

  ; Reuse validates the existing Production authority without creating a new
  ; site. Clean install initializes only the independently selected target.
  ${If} $NetConsoleInstallMode == "REUSE_EXISTING_DATA"
    ExecWait '"$INSTDIR\resources\backend\NetConsoleBackend.exe" --validate-data-root "$NetConsoleDataRoot" --mode reuse --installation-root "$INSTDIR" --diagnostic-log-path "$NetConsoleBackendDiagnosticLogPath" --diagnostic-id "$NetConsoleInstallerDiagnosticId"' $0
  ${ElseIf} $NetConsoleInstallMode == "MIGRATE_EXISTING_DATA"
    ExecWait '"$INSTDIR\resources\backend\NetConsoleBackend.exe" --validate-data-root "$NetConsoleDataRoot" --mode reuse --installation-root "$INSTDIR" --diagnostic-log-path "$NetConsoleBackendDiagnosticLogPath" --diagnostic-id "$NetConsoleInstallerDiagnosticId"' $0
  ${Else}
    ExecWait '"$INSTDIR\resources\backend\NetConsoleBackend.exe" --validate-data-root "$NetConsoleDataRoot" --mode clean-install --installation-root "$INSTDIR" --diagnostic-log-path "$NetConsoleBackendDiagnosticLogPath" --diagnostic-id "$NetConsoleInstallerDiagnosticId"' $0
  ${EndIf}
  StrCpy $NetConsoleInstallerDiagnosticMessage "stage=backend-data-root-initialization mode=$NetConsoleInstallMode exit_code=$0 diagnostic_id=$NetConsoleInstallerDiagnosticId backend_diagnostic_log=$NetConsoleBackendDiagnosticLogPath registry=not-written"
  Call NetConsoleInstallerWriteDiagnostic
  ${If} $0 != 0
    StrCpy $NetConsoleInstallerDiagnosticMessage "stage=backend-data-root-initialization mode=$NetConsoleInstallMode result=failed exit_code=$0 message=Backend 数据根初始化或兼容性校验失败 diagnostic_id=$NetConsoleInstallerDiagnosticId backend_diagnostic_log=$NetConsoleBackendDiagnosticLogPath registry=not-written data-preserved=see-backend-diagnostic"
    Call NetConsoleInstallerAbort
  ${EndIf}
  ExecWait '"$INSTDIR\resources\backend\NetConsoleBackend.exe" --set-runtime-performance-mode "$NetConsoleDataRoot" "$NetConsolePerformanceMode"' $0
  StrCpy $NetConsoleInstallerDiagnosticMessage "stage=runtime-performance-mode exit_code=$0 registry=not-written"
  Call NetConsoleInstallerWriteDiagnostic
  ${If} $0 != 0
    StrCpy $NetConsoleInstallerDiagnosticMessage "stage=runtime-performance-mode result=failed exit_code=$0 registry=not-written"
    Call NetConsoleInstallerAbort
  ${EndIf}
  ; Advisory only: bounded hardware collection must never make an otherwise
  ; valid install fail.  Normal startup reads this profile and never reruns WMI.
  ExecWait '"$INSTDIR\resources\backend\NetConsoleBackend.exe" --collect-host-profile "$NetConsoleDataRoot" --timeout-seconds 4' $0
  ${If} $0 != 0
    DetailPrint "Host environment profile collection skipped: exit_code=$0"
  ${EndIf}
  Call NetConsolePublishDataRootPointer
  ${If} $NetConsoleDataRootPointerResult != "ok"
    StrCpy $NetConsoleInstallerDiagnosticMessage "stage=registry-write-readback result=$NetConsoleDataRootPointerResult registry=restored-or-preserved"
    Call NetConsoleInstallerAbort
  ${EndIf}
  StrCpy $NetConsoleInstallerDiagnosticMessage "stage=complete registry=written-and-readback-verified data_root=$NetConsoleDataRoot"
  Call NetConsoleInstallerWriteDiagnostic
  ${If} $NetConsoleInstallerLogHandle != ""
    FileClose $NetConsoleInstallerLogHandle
    StrCpy $NetConsoleInstallerLogHandle ""
  ${EndIf}
!macroend

; electron-builder compiles an intermediate uninstaller with this include too.
; Its installer-only page handlers must not be emitted in that compilation,
; otherwise NSIS treats their intentional absence from the uninstaller flow as
; a fatal warning.
!ifndef BUILD_UNINSTALLER
Function NetConsoleDataRootPageCreate
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 18u "数据目录"
  Pop $0
  ${NSD_CreateLabel} 0 22u 100% 12u ""
  Pop $NetConsoleDataRootPageModeLabel
  ${NSD_CreateLabel} 0 38u 100% 30u ""
  Pop $NetConsoleDataRootPageSourceLabel
  ${NSD_CreateLabel} 0 72u 100% 12u "目标数据目录："
  Pop $0
  ${NSD_CreateText} 0 88u 76% 14u "$NetConsoleDataRoot"
  Pop $NetConsoleDataRootInput
  ${NSD_CreateButton} 79% 88u 21% 14u "浏览..."
  Pop $NetConsoleDataRootBrowseButton
  ${NSD_OnClick} $NetConsoleDataRootBrowseButton NetConsoleBrowseDataRoot
  ${NSD_CreateLabel} 0 108u 100% 28u ""
  Pop $NetConsoleDataRootStatus
  ${NSD_CreateLabel} 0 142u 100% 10u "NetConsole v${NETCONSOLE_INSTALLER_APP_VERSION} · ${NETCONSOLE_INSTALLER_EDITION} 安装器"
  Pop $0
  Call NetConsoleRefreshDataRootPageText
  Call NetConsoleRefreshDataRootStatus
  nsDialogs::Show
FunctionEnd

Function NetConsoleRefreshDataRootPageText
  ${If} $NetConsoleInstallMode == "REUSE_EXISTING_DATA"
    ${NSD_SetText} $NetConsoleDataRootPageModeLabel "安装方式：沿用已有数据（推荐）"
    ${NSD_SetText} $NetConsoleDataRootPageSourceLabel "当前数据目录：$NetConsoleExistingDataRoot$\r$\n安装器将验证原局点、历史记录和 devices.db。"
    EnableWindow $NetConsoleDataRootInput 0
    EnableWindow $NetConsoleDataRootBrowseButton 0
  ${ElseIf} $NetConsoleInstallMode == "MIGRATE_EXISTING_DATA"
    ${NSD_SetText} $NetConsoleDataRootPageModeLabel "安装方式：迁移已有数据（高级）"
    ${NSD_SetText} $NetConsoleDataRootPageSourceLabel "源数据目录：$NetConsoleExistingDataRoot$\r$\n请选择新的目标目录；源目录保留。"
    EnableWindow $NetConsoleDataRootInput 1
    EnableWindow $NetConsoleDataRootBrowseButton 1
  ${Else}
    ${NSD_SetText} $NetConsoleDataRootPageModeLabel "安装方式：全新安装"
    ${NSD_SetText} $NetConsoleDataRootPageSourceLabel "请选择新的空白目标目录。旧局点、旧 bootstrap 和旧数据库不会被使用。"
    EnableWindow $NetConsoleDataRootInput 1
    EnableWindow $NetConsoleDataRootBrowseButton 1
  ${EndIf}
FunctionEnd

Function NetConsoleBrowseDataRoot
  nsDialogs::SelectFolderDialog "选择 NetConsole 数据存放位置（非系统固定磁盘）" "$NetConsoleDataRoot"
  Pop $0
  ${If} $0 != error
    StrCpy $NetConsoleDataRoot "$0"
    ${NSD_SetText} $NetConsoleDataRootInput "$NetConsoleDataRoot"
    Call NetConsoleRefreshDataRootStatus
  ${EndIf}
FunctionEnd

Function NetConsoleRefreshDataRootStatus
  ${NSD_GetText} $NetConsoleDataRootInput $NetConsoleDataRoot
  ${If} $NetConsoleDataRoot == ""
    ${NSD_SetText} $NetConsoleDataRootStatus "尚未选择数据目录。"
    Return
  ${EndIf}
  Call NetConsoleValidateDataRootLocation
  ${If} $NetConsoleDataRootProbeResult != "ok"
    ${NSD_SetText} $NetConsoleDataRootStatus "$NetConsoleDataRootProbeResult（$NetConsoleDataRootProbeErrorSource 错误码 $NetConsoleDataRootProbeErrorCode）"
    Return
  ${EndIf}
  Call NetConsoleDataRootCheckBusinessData
  ${If} $NetConsoleInstallMode == "FRESH_CLEAN_INSTALL"
    ${If} $NetConsoleDataRootBusinessData == "1"
      ${NSD_SetText} $NetConsoleDataRootStatus "清洁安装目标包含 NetConsole 数据：请选择新的空白目录。"
      Return
    ${EndIf}
  ${ElseIf} $NetConsoleInstallMode == "REUSE_EXISTING_DATA"
    ${If} $NetConsoleDataRootExists != "1"
      ${NSD_SetText} $NetConsoleDataRootStatus "历史数据目录不可访问：请返回选择安装方式。"
      Return
    ${EndIf}
    ${NSD_SetText} $NetConsoleDataRootStatus "沿用模式：将验证 Manifest、Registry、活动局点和 devices.db。"
    Return
  ${ElseIf} $NetConsoleInstallMode == "MIGRATE_EXISTING_DATA"
    ${If} $NetConsoleDataRootBusinessData == "1"
      ${NSD_SetText} $NetConsoleDataRootStatus "迁移目标已有 NetConsole 数据：请选择无冲突目录。"
      Return
    ${EndIf}
  ${EndIf}
  Call NetConsoleDataRootCheckEntries
  ${If} $NetConsoleDataRootHasEntries == "1"
    DetailPrint "目录包含现有普通文件：安装器将保留这些文件；仅在 NetConsole 必需路径发生真实冲突时停止。"
    ${NSD_SetText} $NetConsoleDataRootStatus "目录含普通文件；安装器将保留这些文件。"
    Return
  ${EndIf}
  ${If} $NetConsoleDataRootExists == "1"
    ${NSD_SetText} $NetConsoleDataRootStatus "空目录：可作为 NetConsole 数据根。"
  ${Else}
    ${NSD_SetText} $NetConsoleDataRootStatus "目录不存在：安装器将按此路径创建数据根。"
  ${EndIf}
FunctionEnd

Function NetConsoleValidateDataRootLocation
  StrCpy $NetConsoleDataRootProbeResult "ok"
  StrCpy $NetConsoleDataRootProbeErrorCode "0"
  StrCpy $NetConsoleDataRootProbeErrorSource "NSIS 参数"
  StrCpy $NetConsoleDataRootNormalized ""
  StrCpy $NetConsoleDataRootDriveRoot ""
  StrCpy $NetConsoleDataRootDriveType "0"
  StrCpy $NetConsoleDataRootExists "0"
  DetailPrint "DataRoot selected path: $NetConsoleDataRoot"
  ${If} $NetConsoleDataRoot == ""
    StrCpy $NetConsoleDataRootProbeResult "尚未选择数据目录"
    StrCpy $NetConsoleDataRootProbeErrorCode "NC_PATH_EMPTY"
    Return
  ${EndIf}
  Call NetConsoleNormalizeDataRootPath
  ${If} $NetConsoleDataRootProbeResult != "ok"
    Return
  ${EndIf}
  StrCpy $NetConsoleDataRoot "$NetConsoleDataRootNormalized"
  DetailPrint "DataRoot normalized path: $NetConsoleDataRootNormalized"

  StrCpy $0 "$NetConsoleDataRoot" 2
  ${If} $0 == "\\\\"
    StrCpy $NetConsoleDataRootProbeResult "当前安装仅支持本地固定磁盘，不支持网络共享路径"
    StrCpy $NetConsoleDataRootProbeErrorCode "NC_PATH_NETWORK_SHARE"
    StrCpy $NetConsoleDataRootProbeErrorSource "NSIS 参数"
    Return
  ${EndIf}
  ReadEnvStr $0 "SystemDrive"
  ${If} $0 == ""
    StrCpy $0 "C:"
  ${EndIf}
  StrCpy $1 "$NetConsoleDataRoot" 2
  ${If} $1 == $0
    StrCpy $NetConsoleDataRootProbeResult "当前配置禁止将业务数据存放在系统盘"
    StrCpy $NetConsoleDataRootProbeErrorCode "NC_PATH_SYSTEM_DRIVE"
    StrCpy $NetConsoleDataRootProbeErrorSource "NSIS 参数"
    Return
  ${EndIf}

  ; GetDriveTypeW accepts a root path such as E:\, never E:\NetConsoleData.
  StrCpy $1 "$NetConsoleDataRoot" 3
  StrCpy $NetConsoleDataRootDriveRoot "$1"
  System::Call 'kernel32::GetDriveTypeW(w r1)i.r2'
  StrCpy $NetConsoleDataRootDriveType "$2"
  DetailPrint "DataRoot drive root: $NetConsoleDataRootDriveRoot"
  DetailPrint "DataRoot GetDriveTypeW: $NetConsoleDataRootDriveType"
  ${If} $NetConsoleDataRootDriveType != 3
    ${If} $NetConsoleDataRootDriveType == 1
      StrCpy $NetConsoleDataRootProbeResult "数据目录所在磁盘不可访问，请恢复原磁盘或选择其他磁盘"
      StrCpy $NetConsoleDataRootProbeErrorCode "DRIVE_NO_ROOT_DIR"
    ${ElseIf} $NetConsoleDataRootDriveType == 4
      StrCpy $NetConsoleDataRootProbeResult "数据目录不能位于网络映射盘"
      StrCpy $NetConsoleDataRootProbeErrorCode "DRIVE_REMOTE"
    ${Else}
      StrCpy $NetConsoleDataRootProbeResult "数据目录必须位于本地固定磁盘，不能使用 U 盘、光驱或临时映射盘"
      StrCpy $NetConsoleDataRootProbeErrorCode "NC_PATH_NOT_FIXED_DRIVE"
    ${EndIf}
    StrCpy $NetConsoleDataRootProbeErrorSource "NSIS 参数"
    Return
  ${EndIf}
  IfFileExists "$NetConsoleDataRoot\." 0 +2
    StrCpy $NetConsoleDataRootExists "1"
  DetailPrint "DataRoot directory exists: $NetConsoleDataRootExists"
  Return
FunctionEnd

Function NetConsoleNormalizeDataRootPath
  StrCpy $NetConsoleDataRootProbeResult "ok"
  StrCpy $NetConsoleDataRootProbeErrorCode "0"
  StrCpy $NetConsoleDataRootProbeErrorSource "无"
  StrCpy $NetConsoleDataRootNormalized ""

  ; Only rooted local drive paths are accepted.  Do not resolve a relative path
  ; against the installer working directory and accidentally publish that value.
  StrCpy $0 "$NetConsoleDataRoot" 2 1
  StrCmp $0 ":\" 0 NetConsoleDataRootPathNotAbsolute

  ; GetFullPathNameW resolves syntax without requiring the target to exist.
  ; Reject Win32-invalid characters locally because the target may not exist yet.
  StrLen $0 "$NetConsoleDataRoot"
  StrCpy $1 "2"
  NetConsoleDataRootPathCharacterLoop:
  IntCmp $1 $0 NetConsoleDataRootPathCharacterValid NetConsoleDataRootPathCharacterCheck NetConsoleDataRootPathCharacterValid
  NetConsoleDataRootPathCharacterCheck:
  StrCpy $2 "$NetConsoleDataRoot" 1 $1
  StrCmp $2 "<" NetConsoleDataRootPathInvalidCharacter
  StrCmp $2 ">" NetConsoleDataRootPathInvalidCharacter
  StrCmp $2 "$\"" NetConsoleDataRootPathInvalidCharacter
  StrCmp $2 "|" NetConsoleDataRootPathInvalidCharacter
  StrCmp $2 "?" NetConsoleDataRootPathInvalidCharacter
  StrCmp $2 "*" NetConsoleDataRootPathInvalidCharacter
  StrCmp $2 ":" NetConsoleDataRootPathInvalidCharacter
  IntOp $1 $1 + 1
  Goto NetConsoleDataRootPathCharacterLoop

  NetConsoleDataRootPathCharacterValid:
  StrCpy $0 "$NetConsoleDataRoot"
  System::Call 'kernel32::GetFullPathNameW(w r0, i ${NSIS_MAX_STRLEN}, w .r1, p 0)i.r2'
  IntCmp $2 0 NetConsoleDataRootPathWinApiFailed 0 0
  IntCmp $2 ${NSIS_MAX_STRLEN} NetConsoleDataRootPathTooLong NetConsoleDataRootPathNormalized NetConsoleDataRootPathTooLong

  NetConsoleDataRootPathNormalized:
  StrCpy $NetConsoleDataRootNormalized "$1"
  Return

  NetConsoleDataRootPathNotAbsolute:
  StrCpy $NetConsoleDataRootProbeResult "数据目录必须是绝对本地路径"
  StrCpy $NetConsoleDataRootProbeErrorCode "NC_PATH_NOT_ABSOLUTE"
  StrCpy $NetConsoleDataRootProbeErrorSource "NSIS 参数"
  Return

  NetConsoleDataRootPathInvalidCharacter:
  StrCpy $NetConsoleDataRootProbeResult "数据目录包含非法路径字符"
  StrCpy $NetConsoleDataRootProbeErrorCode "NC_PATH_INVALID_CHARACTER"
  StrCpy $NetConsoleDataRootProbeErrorSource "NSIS 参数"
  Return

  NetConsoleDataRootPathTooLong:
  StrCpy $NetConsoleDataRootProbeResult "数据目录路径过长"
  StrCpy $NetConsoleDataRootProbeErrorCode "NC_PATH_TOO_LONG"
  StrCpy $NetConsoleDataRootProbeErrorSource "NSIS 参数"
  Return

  NetConsoleDataRootPathWinApiFailed:
  System::Call 'kernel32::GetLastError()i.r0'
  StrCpy $NetConsoleDataRootProbeResult "数据目录路径无法规范化"
  StrCpy $NetConsoleDataRootProbeErrorCode "$0"
  StrCpy $NetConsoleDataRootProbeErrorSource "Windows API"
FunctionEnd

Function NetConsoleDataRootCheckEntries
  ; IfFileExists "$root\*.*" reports some empty Windows directories as
  ; non-empty. Enumerate the directory and ignore only the virtual dot entries.
  StrCpy $NetConsoleDataRootHasEntries "0"
  ClearErrors
  FindFirst $NetConsoleDataRootFindHandle $NetConsoleDataRootFindName "$NetConsoleDataRoot\*"
  IfErrors NetConsoleDataRootCheckEntriesEmpty

  NetConsoleDataRootCheckEntriesLoop:
  StrCmp $NetConsoleDataRootFindName "." NetConsoleDataRootCheckEntriesNext
  StrCmp $NetConsoleDataRootFindName ".." NetConsoleDataRootCheckEntriesNext
  ; Old v1.4.3 installers could leave these fixed-name probe files behind.
  ; They are never business data and must not force a nested data root.
  StrCmp $NetConsoleDataRootFindName ".netconsole-installer-write-test.tmp" NetConsoleDataRootCheckEntriesNext
  StrCmp $NetConsoleDataRootFindName ".netconsole-installer-rename-test.tmp" NetConsoleDataRootCheckEntriesNext
  DetailPrint "DataRoot existing entry: $NetConsoleDataRootFindName"
  StrCpy $NetConsoleDataRootHasEntries "1"

  NetConsoleDataRootCheckEntriesNext:
  ClearErrors
  FindNext $NetConsoleDataRootFindHandle $NetConsoleDataRootFindName
  IfErrors NetConsoleDataRootCheckEntriesDone
  Goto NetConsoleDataRootCheckEntriesLoop

  NetConsoleDataRootCheckEntriesDone:
  FindClose $NetConsoleDataRootFindHandle
  NetConsoleDataRootCheckEntriesEmpty:
FunctionEnd

Function NetConsoleRunDataRootProbe
  StrCpy $NetConsoleDataRootProbeResult "ok"
  StrCpy $NetConsoleDataRootProbeErrorCode "0"
  StrCpy $NetConsoleDataRootProbeErrorSource "Windows API"
  StrCpy $NetConsoleDataRootProbeExpected "NetConsole-install-probe-v1"

  ClearErrors
  CreateDirectory "$NetConsoleDataRoot"
  IfErrors NetConsoleDataRootProbeCreateDirectoryFailed

  System::Call 'kernel32::GetCurrentProcessId()i.r0'
  StrCpy $NetConsoleDataRootProbePid "$0"

  NetConsoleDataRootProbeChooseName:
  System::Call 'kernel32::GetTickCount()i.r0'
  StrCpy $NetConsoleDataRootProbeTick "$0"
  StrCpy $NetConsoleDataRootProbeSource "$NetConsoleDataRoot\.netconsole-install-probe-$NetConsoleDataRootProbePid-$NetConsoleDataRootProbeTick.tmp"
  StrCpy $NetConsoleDataRootProbeTarget "$NetConsoleDataRootProbeSource.renamed"
  IfFileExists "$NetConsoleDataRootProbeSource" NetConsoleDataRootProbeNameCollision 0
  IfFileExists "$NetConsoleDataRootProbeTarget" NetConsoleDataRootProbeNameCollision NetConsoleDataRootProbeNameReady

  NetConsoleDataRootProbeNameCollision:
  Sleep 1
  Goto NetConsoleDataRootProbeChooseName

  NetConsoleDataRootProbeNameReady:
  ClearErrors
  FileOpen $0 "$NetConsoleDataRootProbeSource" w
  IfErrors NetConsoleDataRootProbeCreateFileFailed
  ClearErrors
  FileWrite $0 "$NetConsoleDataRootProbeExpected"
  IfErrors NetConsoleDataRootProbeWriteFailed
  System::Call 'kernel32::FlushFileBuffers(p r0)i.r1'
  StrCmp $1 0 NetConsoleDataRootProbeFlushFailed
  ClearErrors
  FileClose $0
  IfErrors NetConsoleDataRootProbeCloseFailed

  System::Call 'kernel32::MoveFileExW(w "$NetConsoleDataRootProbeSource", w "$NetConsoleDataRootProbeTarget", i 0)i.r1'
  StrCmp $1 0 0 +3
    System::Call 'kernel32::GetLastError()i.r0'
    Goto NetConsoleDataRootProbeRenameFailed
  IfFileExists "$NetConsoleDataRootProbeTarget" 0 NetConsoleDataRootProbeTargetMissing

  ClearErrors
  FileOpen $0 "$NetConsoleDataRootProbeTarget" r
  IfErrors NetConsoleDataRootProbeReadFailed
  ClearErrors
  FileRead $0 $NetConsoleDataRootProbeActual
  IfErrors NetConsoleDataRootProbeReadOpenFailed
  FileClose $0
  StrCmp $NetConsoleDataRootProbeActual $NetConsoleDataRootProbeExpected 0 NetConsoleDataRootProbeContentMismatch

  ClearErrors
  Delete "$NetConsoleDataRootProbeTarget"
  IfErrors NetConsoleDataRootProbeCleanupFailed
  Return

  NetConsoleDataRootProbeCreateDirectoryFailed:
  System::Call 'kernel32::GetLastError()i.r0'
  StrCpy $NetConsoleDataRootProbeErrorCode "$0"
  StrCpy $NetConsoleDataRootProbeResult "目录无法创建"
  Return

  NetConsoleDataRootProbeCreateFileFailed:
  System::Call 'kernel32::GetLastError()i.r0'
  StrCpy $NetConsoleDataRootProbeErrorCode "$0"
  StrCmp $NetConsoleDataRootProbeErrorCode 5 0 +3
    StrCpy $NetConsoleDataRootProbeResult "目录不可写（访问被拒绝）"
    Return
  StrCpy $NetConsoleDataRootProbeResult "临时探测文件创建失败"
  Return

  NetConsoleDataRootProbeWriteFailed:
  System::Call 'kernel32::GetLastError()i.r1'
  StrCpy $NetConsoleDataRootProbeErrorCode "$1"
  FileClose $0
  Delete "$NetConsoleDataRootProbeSource"
  StrCpy $NetConsoleDataRootProbeResult "临时探测文件写入失败"
  Return

  NetConsoleDataRootProbeFlushFailed:
  System::Call 'kernel32::GetLastError()i.r1'
  StrCpy $NetConsoleDataRootProbeErrorCode "$1"
  FileClose $0
  Delete "$NetConsoleDataRootProbeSource"
  StrCpy $NetConsoleDataRootProbeResult "临时探测文件刷新失败"
  Return

  NetConsoleDataRootProbeCloseFailed:
  System::Call 'kernel32::GetLastError()i.r0'
  StrCpy $NetConsoleDataRootProbeErrorCode "$0"
  Delete "$NetConsoleDataRootProbeSource"
  StrCpy $NetConsoleDataRootProbeResult "临时探测文件关闭失败"
  Return

  NetConsoleDataRootProbeRenameFailed:
  StrCpy $NetConsoleDataRootProbeErrorCode "$0"
  Delete "$NetConsoleDataRootProbeSource"
  StrCmp $NetConsoleDataRootProbeErrorCode 5 0 +3
    StrCpy $NetConsoleDataRootProbeResult "同目录重命名被权限阻止"
    Return
  StrCmp $NetConsoleDataRootProbeErrorCode 32 0 +3
    StrCpy $NetConsoleDataRootProbeResult "临时探测文件正在被其他程序占用"
    Return
  StrCmp $NetConsoleDataRootProbeErrorCode 50 0 +3
    StrCpy $NetConsoleDataRootProbeResult "文件系统不支持同目录文件重命名"
    Return
  StrCpy $NetConsoleDataRootProbeResult "同目录临时文件重命名失败"
  Return

  NetConsoleDataRootProbeTargetMissing:
  StrCpy $NetConsoleDataRootProbeErrorCode "2"
  StrCpy $NetConsoleDataRootProbeErrorSource "NSIS 逻辑"
  Delete "$NetConsoleDataRootProbeSource"
  Delete "$NetConsoleDataRootProbeTarget"
  StrCpy $NetConsoleDataRootProbeResult "重命名后的临时文件不存在"
  Return

  NetConsoleDataRootProbeReadFailed:
  System::Call 'kernel32::GetLastError()i.r0'
  StrCpy $NetConsoleDataRootProbeErrorCode "$0"
  Delete "$NetConsoleDataRootProbeTarget"
  StrCpy $NetConsoleDataRootProbeResult "重命名后的临时文件无法读取"
  Return

  NetConsoleDataRootProbeReadOpenFailed:
  System::Call 'kernel32::GetLastError()i.r1'
  StrCpy $NetConsoleDataRootProbeErrorCode "$1"
  FileClose $0
  Delete "$NetConsoleDataRootProbeTarget"
  StrCpy $NetConsoleDataRootProbeResult "重命名后的临时文件读取失败"
  Return

  NetConsoleDataRootProbeContentMismatch:
  Delete "$NetConsoleDataRootProbeTarget"
  StrCpy $NetConsoleDataRootProbeErrorCode "0"
  StrCpy $NetConsoleDataRootProbeErrorSource "NSIS 逻辑"
  StrCpy $NetConsoleDataRootProbeResult "重命名后的临时文件内容校验失败"
  Return

  NetConsoleDataRootProbeCleanupFailed:
  System::Call 'kernel32::GetLastError()i.r0'
  StrCpy $NetConsoleDataRootProbeErrorCode "$0"
  StrCpy $NetConsoleDataRootProbeResult "临时探测文件清理失败"
FunctionEnd

Function NetConsoleDataRootPageLeave
  ${NSD_GetText} $NetConsoleDataRootInput $NetConsoleDataRoot
  Call NetConsoleValidateDataRootLocation
  ${If} $NetConsoleDataRootProbeResult != "ok"
    DetailPrint "DataRoot location validation failed: step=$NetConsoleDataRootProbeResult error_source=$NetConsoleDataRootProbeErrorSource error_code=$NetConsoleDataRootProbeErrorCode"
    MessageBox MB_ICONSTOP "数据目录位置校验失败。$\r$\n失败步骤：$NetConsoleDataRootProbeResult$\r$\n错误来源：$NetConsoleDataRootProbeErrorSource$\r$\n错误码：$NetConsoleDataRootProbeErrorCode"
    Abort
  ${EndIf}
  Call NetConsoleDataRootCheckBusinessData
  Call NetConsoleDataRootPathsMatch
  ${If} $NetConsoleInstallMode == "FRESH_CLEAN_INSTALL"
    ${If} $NetConsoleDataRootPathsMatch == "1"
      MessageBox MB_ICONSTOP "清洁安装不能选择原有业务数据根。请选择新的空白目标，或返回选择沿用已有数据。"
      Abort
    ${EndIf}
    ${If} $NetConsoleDataRootBusinessData == "1"
      MessageBox MB_ICONSTOP "清洁安装目标包含现有或不明确的 NetConsole 数据。不会删除或覆盖原数据，请选择新根。"
      Abort
    ${EndIf}
  ${ElseIf} $NetConsoleInstallMode == "REUSE_EXISTING_DATA"
    ${If} $NetConsoleDataRootPathsMatch != "1"
      MessageBox MB_ICONSTOP "沿用已有数据模式不执行迁移。请选择原 DataRoot，或返回明确选择迁移已有数据。"
      Abort
    ${EndIf}
    ${If} $NetConsoleDataRootExists != "1"
      MessageBox MB_ICONSTOP "历史数据目录不可访问。请恢复原磁盘后重试，或返回选择全新安装；安装器不会创建空替代目录。"
      Abort
    ${EndIf}
  ${Else}
    ${If} $NetConsoleDataRootPathsMatch == "1"
      MessageBox MB_ICONSTOP "迁移目标不能与源 DataRoot 相同，请选择新的目标目录。"
      Abort
    ${EndIf}
    ${If} $NetConsoleDataRootBusinessData == "1"
      MessageBox MB_ICONSTOP "迁移目标包含现有 NetConsole 数据，为避免覆盖请另选无冲突目标。"
      Abort
    ${EndIf}
    StrCpy $NetConsoleDataRootChanged "1"
  ${EndIf}

  ; Enumerate before the capability probe for diagnostics only. Ordinary files
  ; are preserved and do not block installation unless the selected mode finds
  ; a real conflict with a required NetConsole path.
  Call NetConsoleDataRootCheckEntries
  Call NetConsoleRunDataRootProbe
  ${If} $NetConsoleDataRootProbeResult != "ok"
    DetailPrint "DataRoot probe failed: step=$NetConsoleDataRootProbeResult error_source=$NetConsoleDataRootProbeErrorSource error_code=$NetConsoleDataRootProbeErrorCode"
    MessageBox MB_ICONSTOP "数据目录校验失败。$\r$\n失败步骤：$NetConsoleDataRootProbeResult$\r$\n错误来源：$NetConsoleDataRootProbeErrorSource$\r$\n错误码：$NetConsoleDataRootProbeErrorCode$\r$\n$\r$\n请关闭 NetConsole、Agent 和 Backend 后重试，并检查目录权限或文件系统。不要删除已有数据。"
    Abort
  ${EndIf}
FunctionEnd

!endif

!endif
