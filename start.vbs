' start.vbs
' Silently start AttendanceHelper with real GUI pythonw (no CMD window).
' uv's .venv\Scripts\pythonw.exe is a console shim and will flash a black window.

Option Explicit

Dim sh, fso, dir, venv, cfg, home, pythonw, script, site, line, pos, killCmd, runCmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

dir = fso.GetParentFolderName(WScript.ScriptFullName)
venv = dir & "\.venv"
cfg = venv & "\pyvenv.cfg"
script = dir & "\attendance_tray.py"
site = venv & "\Lib\site-packages"

If Not fso.FileExists(script) Then
  WScript.Quit 1
End If
If Not fso.FileExists(cfg) Then
  WScript.Quit 1
End If

home = ""
For Each line In Split(fso.OpenTextFile(cfg, 1, False, 0).ReadAll(), vbLf)
  line = Trim(Replace(line, vbCr, ""))
  If LCase(Left(line, 4)) = "home" Then
    pos = InStr(line, "=")
    If pos > 0 Then
      home = Trim(Mid(line, pos + 1))
    End If
  End If
Next

If home = "" Then
  WScript.Quit 1
End If

pythonw = home & "\pythonw.exe"
If Not fso.FileExists(pythonw) Then
  WScript.Quit 1
End If

' Stop old instances quietly
killCmd = "powershell -NoProfile -WindowStyle Hidden -Command ""Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*attendance_tray.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"""
sh.Run killCmd, 0, True
WScript.Sleep 400

' Ensure venv site-packages are used by the real interpreter
sh.Environment("Process")("VIRTUAL_ENV") = venv
sh.Environment("Process")("PYTHONPATH") = site
sh.Environment("Process")("PYTHONUTF8") = "1"

' WindowStyle 0 = completely hidden (no console)
runCmd = """" & pythonw & """ """ & script & """"
sh.CurrentDirectory = dir
sh.Run runCmd, 0, False
