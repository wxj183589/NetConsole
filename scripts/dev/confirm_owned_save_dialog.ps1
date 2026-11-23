param(
    [Parameter(Mandatory = $true)][string]$MainWindowHandle,
    [Parameter(Mandatory = $true)][string]$ExpectedFileName
)
$ErrorActionPreference = 'Stop'
if ($env:NETCONSOLE_RUNTIME_MODE -ne 'test' -or $env:NETCONSOLE_ISOLATED_SMOKE -ne '1') {
    throw 'Save dialog acceptance helper is test-only'
}
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class OwnedSaveDialog {
    public delegate bool Visitor(IntPtr handle, IntPtr data);
    [DllImport("user32.dll")] static extern bool EnumWindows(Visitor visit, IntPtr data);
    [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr handle, uint command);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr handle, StringBuilder name, int capacity);
    public static IntPtr Find(IntPtr owner) {
        IntPtr found = IntPtr.Zero;
        EnumWindows((handle, data) => {
            var name = new StringBuilder(256);
            GetClassName(handle, name, name.Capacity);
            if (name.ToString() != "#32770") return true;
            var parent = handle;
            for (int depth = 0; depth < 8; depth++) {
                parent = GetWindow(parent, 4);
                if (parent == IntPtr.Zero) break;
                if (parent == owner) { found = handle; return false; }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@
$ownerHandle = [IntPtr]::new([Int64]::Parse($MainWindowHandle))
$deadline = [DateTime]::UtcNow.AddSeconds(10)
do {
    $dialogHandle = [OwnedSaveDialog]::Find($ownerHandle)
    if ($dialogHandle -ne [IntPtr]::Zero) { break }
    Start-Sleep -Milliseconds 100
} while ([DateTime]::UtcNow -lt $deadline)
if ($dialogHandle -eq [IntPtr]::Zero) { throw 'No Save As dialog owned by acceptance window' }
$dialogElement = [System.Windows.Automation.AutomationElement]::FromHandle($dialogHandle)
do {
  $elements = $dialogElement.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  $filenameMatches = $false
  $saveButton = $null
  foreach ($element in $elements) {
    $valuePattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$valuePattern)) {
        if ([System.IO.Path]::GetFileName($valuePattern.Current.Value.Trim('"')) -eq $ExpectedFileName) { $filenameMatches = $true }
    }
    if (($element.Current.AutomationId -eq '1' -or $element.Current.Name -match '^(保存|Save)(\(.*\))?$') -and $element.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button) {
        $saveButton = $element
    }
  }
  if ($filenameMatches -and $null -ne $saveButton) { break }
  Start-Sleep -Milliseconds 100
} while ([DateTime]::UtcNow -lt $deadline)
if (-not $filenameMatches -or $null -eq $saveButton) {
    foreach ($element in $elements) {
        if ($element.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit -or
            $element.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button) {
            Write-Output ($element.Current.AutomationId + ': ' + $element.Current.Name)
        }
    }
    throw 'Owned dialog filename or Save button did not match'
}
$invoke = $saveButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
$invoke.Invoke()
Write-Output 'OWNED_NATIVE_SAVE_INVOKED'
