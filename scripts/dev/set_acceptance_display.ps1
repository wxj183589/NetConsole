param([int]$Width = 0, [int]$Height = 0, [switch]$Apply)
$ErrorActionPreference = 'Stop'
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class AcceptanceDisplay {
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
 public struct Mode {
  [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string device;
  public short spec,driver,size,extra; public int fields;
  public int x,y,orientation,fixedOutput;
  public short color,duplex,yres,tt,collate;
  [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string form;
  public short dpi; public int bits,width,height,flags,frequency,icmMethod,icmIntent,media,dither,reserved1,reserved2,panningWidth,panningHeight;
 }
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern bool EnumDisplaySettings(string name,int mode,ref Mode value);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int ChangeDisplaySettingsEx(string name,ref Mode value,IntPtr hwnd,int flags,IntPtr param);
 public static Mode Current() { var value=new Mode(); value.size=(short)Marshal.SizeOf(value); if(!EnumDisplaySettings(null,-1,ref value)) throw new Exception("Cannot read current display"); return value; }
}
'@
$current = [AcceptanceDisplay]::Current()
if ($Width -eq 0 -or $Height -eq 0) {
    @{ width=$current.width; height=$current.height; frequency=$current.frequency } | ConvertTo-Json -Compress
    exit 0
}
$mode = $current
$mode.width = $Width
$mode.height = $Height
$mode.fields = 0x80000 -bor 0x100000
$test = [AcceptanceDisplay]::ChangeDisplaySettingsEx($null, [ref]$mode, [IntPtr]::Zero, 2, [IntPtr]::Zero)
if ($test -ne 0) { throw "Display mode unavailable: $test" }
if ($Apply) {
    # Flags=0 changes the active mode only; no CDS_UPDATEREGISTRY persistence.
    $result = [AcceptanceDisplay]::ChangeDisplaySettingsEx($null, [ref]$mode, [IntPtr]::Zero, 0, [IntPtr]::Zero)
    if ($result -ne 0) { throw "Display change failed: $result" }
}
$actual = [AcceptanceDisplay]::Current()
@{ test=$test; applied=[bool]$Apply; width=$actual.width; height=$actual.height; originalWidth=$current.width; originalHeight=$current.height } | ConvertTo-Json -Compress
