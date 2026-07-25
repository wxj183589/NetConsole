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
  VIAddVersionKey /LANG=1033 "InstallerPolicy" "${NETCONSOLE_INSTALLER_POLICY}"
  VIAddVersionKey /LANG=1033 "InstallerPolicySHA256" "${NETCONSOLE_INSTALLER_POLICY_SHA256}"
!macroend

!ifndef BUILD_UNINSTALLER
Var NetConsoleDataRoot
Var NetConsoleExistingDataRoot
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
!endif

!macro customInit
  DetailPrint "Installer identity: app=${NETCONSOLE_INSTALLER_APP_VERSION} commit=${NETCONSOLE_INSTALLER_GIT_COMMIT} build_time=${NETCONSOLE_INSTALLER_BUILD_TIME} build_id=${NETCONSOLE_INSTALLER_BUILD_ID} policy=${NETCONSOLE_INSTALLER_POLICY}"
  InitPluginsDir
  File /oname=$PLUGINSDIR\netconsole-installer-build.json "${NETCONSOLE_INSTALLER_MANIFEST_PATH}"
  File /oname=$PLUGINSDIR\netconsole-installer-data-root.nsh "${NETCONSOLE_INSTALLER_POLICY_SOURCE_PATH}"
  ReadRegStr $NetConsoleExistingDataRoot HKLM "Software\NetConsole" "DataRoot"
  ${If} $NetConsoleExistingDataRoot != ""
    StrCpy $NetConsoleDataRoot "$NetConsoleExistingDataRoot"
  ${Else}
    ; D: is only a suggestion when it is an actual fixed disk.  The page blocks
    ; the install until a non-system fixed disk has been selected and validated.
    StrCpy $0 "D:\"
    System::Call 'kernel32::GetDriveTypeW(w r0)i.r1'
    ${If} $1 == 3
      StrCpy $NetConsoleDataRoot "D:\NetConsoleData"
    ${Else}
      StrCpy $NetConsoleDataRoot ""
    ${EndIf}
  ${EndIf}
  StrCpy $NetConsoleDataRootChanged "0"
!macroend

!macro customPageAfterChangeDir
  Page custom NetConsoleDataRootPageCreate NetConsoleDataRootPageLeave
!macroend

!macro customInstall
  Call NetConsoleValidateDataRootLocation
  ${If} $NetConsoleDataRootProbeResult != "ok"
    DetailPrint "DataRoot location validation failed: step=$NetConsoleDataRootProbeResult error_source=$NetConsoleDataRootProbeErrorSource error_code=$NetConsoleDataRootProbeErrorCode"
    Abort "数据目录位置校验失败：$NetConsoleDataRootProbeResult（错误来源：$NetConsoleDataRootProbeErrorSource；错误码：$NetConsoleDataRootProbeErrorCode）。请选择非系统盘上的本地固定磁盘目录。"
  ${EndIf}
  ; A relocation is never a pointer-only update.  The packaged helper stages,
  ; verifies SQLite files and publishes the new root before this registry value
  ; changes.  The source root remains untouched on every failure path.
  ${If} $NetConsoleDataRootChanged == "1"
    IfFileExists "$NetConsoleExistingDataRoot\*.*" +2 0
      Abort "已配置的数据目录当前不可用。请恢复磁盘连接或重新选择数据目录。"
    DetailPrint "正在迁移现有 NetConsole 数据；旧数据将保留为只读备份。"
    ExecWait '"$INSTDIR\resources\backend\NetConsoleBackend.exe" --migrate-data-root --source "$NetConsoleExistingDataRoot" --target "$NetConsoleDataRoot" --installation-root "$INSTDIR"' $0
    ${If} $0 != 0
      Abort "NetConsole 数据迁移失败，旧数据目录未改变。安装器不会修改 DataRoot。"
    ${EndIf}
  ${EndIf}
  Call NetConsoleRunDataRootProbe
  ${If} $NetConsoleDataRootProbeResult != "ok"
    DetailPrint "DataRoot probe failed: step=$NetConsoleDataRootProbeResult error_source=$NetConsoleDataRootProbeErrorSource error_code=$NetConsoleDataRootProbeErrorCode"
    Abort "数据目录校验失败：$NetConsoleDataRootProbeResult（错误来源：$NetConsoleDataRootProbeErrorSource；错误码：$NetConsoleDataRootProbeErrorCode）。请关闭 NetConsole、Agent 和 Backend 后重试；不要删除已有数据。"
  ${EndIf}
  ; This command validates the selected root and creates/checks the storage
  ; manifest before the registry pointer is published. First launch therefore
  ; never owns data-root initialization.
  ExecWait '"$INSTDIR\resources\backend\NetConsoleBackend.exe" --validate-data-root "$NetConsoleDataRoot" --installation-root "$INSTDIR"' $0
  ${If} $0 != 0
    Abort "Backend 数据根初始化或兼容性校验失败（退出代码 $0）。请检查安装日志；不要删除已有数据。"
  ${EndIf}
  WriteRegStr HKLM "Software\NetConsole" "DataRoot" "$NetConsoleDataRoot"
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
  ${NSD_CreateLabel} 0 0 100% 28u "NetConsole 会在此目录保存局点数据库、MR 原始日志、采集文件、分析结果、报告和备份，数据量可能持续增长。请选择容量充足的非系统固定磁盘。"
  Pop $0
  ${NSD_CreateLabel} 0 34u 100% 12u "数据存放位置（建议至少 100 GB 可用空间）："
  Pop $0
  ${NSD_CreateText} 0 50u 76% 12u "$NetConsoleDataRoot"
  Pop $NetConsoleDataRootInput
  ${NSD_CreateButton} 79% 50u 21% 12u "浏览..."
  Pop $0
  ${NSD_OnClick} $0 NetConsoleBrowseDataRoot
  ${NSD_CreateLabel} 0 72u 100% 36u ""
  Pop $NetConsoleDataRootStatus
  ${NSD_CreateLabel} 0 112u 100% 12u "安装器：v${NETCONSOLE_INSTALLER_APP_VERSION} · ${NETCONSOLE_INSTALLER_GIT_SHORT} · ${NETCONSOLE_INSTALLER_BUILD_TIME} · ${NETCONSOLE_INSTALLER_BUILD_ID}"
  Pop $0
  Call NetConsoleRefreshDataRootStatus
  nsDialogs::Show
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
    ${NSD_SetText} $NetConsoleDataRootStatus "尚未选择数据目录。安装不会写入 C 盘或 AppData。"
    Return
  ${EndIf}
  Call NetConsoleValidateDataRootLocation
  ${If} $NetConsoleDataRootProbeResult != "ok"
    ${NSD_SetText} $NetConsoleDataRootStatus "$NetConsoleDataRootProbeResult（$NetConsoleDataRootProbeErrorSource 错误码 $NetConsoleDataRootProbeErrorCode）"
    Return
  ${EndIf}
  IfFileExists "$NetConsoleDataRoot\config\storage-manifest.json" 0 +3
    ${NSD_SetText} $NetConsoleDataRootStatus "发现现有 NetConsole 数据：将继续使用，不会覆盖局点和采集文件。"
    Return
  Call NetConsoleDataRootCheckEntries
  ${If} $NetConsoleDataRootHasEntries == "1"
    ${NSD_SetText} $NetConsoleDataRootStatus "目录包含现有普通文件：安装器将保留这些文件；仅在 NetConsole 必需路径发生真实冲突时停止。"
    Return
  ${EndIf}
  ${If} $NetConsoleDataRootExists == "1"
    ${NSD_SetText} $NetConsoleDataRootStatus "空目录：将直接使用此目录作为 NetConsole 数据根。"
  ${Else}
    ${NSD_SetText} $NetConsoleDataRootStatus "目录不存在：将在此精确路径创建 NetConsole 数据根，不会追加子目录。"
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
    StrCpy $NetConsoleDataRootProbeResult "数据目录必须位于本地固定磁盘，不能使用 U 盘、光驱或临时映射盘"
    StrCpy $NetConsoleDataRootProbeErrorCode "NC_PATH_NOT_FIXED_DRIVE"
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
  ; Enumerate before the capability probe for diagnostics only. Ordinary files
  ; are preserved and do not block installation unless the Backend later finds
  ; a real conflict with a required NetConsole path.
  Call NetConsoleDataRootCheckEntries
  Call NetConsoleRunDataRootProbe
  ${If} $NetConsoleDataRootProbeResult != "ok"
    DetailPrint "DataRoot probe failed: step=$NetConsoleDataRootProbeResult error_source=$NetConsoleDataRootProbeErrorSource error_code=$NetConsoleDataRootProbeErrorCode"
    MessageBox MB_ICONSTOP "数据目录校验失败。$\r$\n失败步骤：$NetConsoleDataRootProbeResult$\r$\n错误来源：$NetConsoleDataRootProbeErrorSource$\r$\n错误码：$NetConsoleDataRootProbeErrorCode$\r$\n$\r$\n请关闭 NetConsole、Agent 和 Backend 后重试，并检查目录权限或文件系统。不要删除已有数据。"
    Abort
  ${EndIf}
  ${If} $NetConsoleExistingDataRoot != ""
  ${AndIf} $NetConsoleExistingDataRoot != $NetConsoleDataRoot
    MessageBox MB_ICONEXCLAMATION|MB_YESNO "当前数据目录：$NetConsoleExistingDataRoot$\r$\n新数据目录：$NetConsoleDataRoot$\r$\n$\r$\n继续将执行完整复制、SQLite 校验和原子发布；旧目录将保留，绝不自动删除。是否继续？" IDYES +2
      Abort
    StrCpy $NetConsoleDataRootChanged "1"
  ${EndIf}
FunctionEnd

!endif
