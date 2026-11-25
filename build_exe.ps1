# Copyright (c) iGroup. All rights reserved.
# @author Kai @date 2026/10/26 10:43
# @description 打包单 EXE 考勤助手及内置看板静态资源。
# 打出单文件 exe（方便发给同事）以及目录版（IT 部署，冷启动更快）。
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
#   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -OnefileOnly
#   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -OnedirOnly

param(
    [switch]$OnefileOnly,
    [switch]$OnedirOnly,
    [string]$OutputDirectory = "dist",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
# @author Kai @date 2026/10/26 11:00：Windows Qt 使用系统 ICU；排除工具运行时的 Poppler DLL 搜索路径，防止同名依赖污染。
$cleanBuildPaths = $env:PATH -split ';' | Where-Object { $_ -and $_ -notlike '*codex-runtimes*' }
$env:PATH = "$env:WINDIR\System32;" + ($cleanBuildPaths -join ';')

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Missing .venv"
    exit 1
}

# @author Kai @date 2026/10/26 11:19：解析 JSON 路径并先校验，避免空路径或错误盘符进入 PyInstaller。
$nativeDependenciesJson = & $venvPython (Join-Path $PSScriptRoot "build_dependencies.py")
if ($LASTEXITCODE -ne 0) { throw "Unable to locate Python OpenSSL DLLs" }
$nativeDependencies = ($nativeDependenciesJson -join "`n") | ConvertFrom-Json
foreach ($dependencyPath in @($nativeDependencies.crypto, $nativeDependencies.ssl)) {
    if (!(Test-Path -LiteralPath $dependencyPath -PathType Leaf)) {
        throw "Missing native DLL: $dependencyPath"
    }
    Write-Host "Native DLL: $dependencyPath"
}
# @author Kai @date 2026/10/26 11:24：优先复用现有构建工具，uv 虚拟环境不一定包含 pip。
& $venvPython -c "import PyInstaller; print('PyInstaller: ' + PyInstaller.__version__)"
$hasPyInstaller = $LASTEXITCODE -eq 0
if (!$hasPyInstaller) {
    if ($ValidateOnly) { throw "PyInstaller is missing from the build environment" }
    Write-Host "==> Installing PyInstaller ..."
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    $userUv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if ($uvCommand) {
        & $uvCommand.Source pip install --python $venvPython -q "pyinstaller>=6.22"
    } elseif (Test-Path -LiteralPath $userUv) {
        & $userUv pip install --python $venvPython -q "pyinstaller>=6.22"
    } else {
        # 无 uv 时由 Python 标准库补齐 pip，再安装构建工具。
        & $venvPython -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { throw "pip is unavailable; install uv or bootstrap pip first" }
        & $venvPython -m pip install -q "pyinstaller>=6.22"
    }
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed" }
} else {
    Write-Host "==> Using installed PyInstaller"
}
if ($ValidateOnly) { return }

$dist = Join-Path $PSScriptRoot $OutputDirectory
$work = Join-Path $PSScriptRoot "build"
New-Item -ItemType Directory -Force -Path $dist | Out-Null

$configExample = Join-Path $PSScriptRoot "config.example.json"
$petDir = Join-Path $PSScriptRoot "attendance_helper\pet"
$entry = Join-Path $PSScriptRoot "attendance_tray.py"
# @author Kai @date 2026/10/26 10:57：显式绑定 Python 配套 OpenSSL，避免从系统 PATH 混入 Poppler 等工具的同名 DLL。

# Keep package small: do NOT --collect-all PySide6 (pulls WebEngine/3D/etc).
$commonArgs = @(
    "--noconfirm",
    "--windowed",
    "--name", "AttendanceHelper",
    "--distpath", $dist,
    "--workpath", $work,
    "--specpath", $work,
    "--paths", $PSScriptRoot,
    "--add-binary", ($nativeDependencies.crypto + ";."),
    "--add-binary", ($nativeDependencies.ssl + ";."),
    # 内置看板模块与资源，运行时无需 DeskHub.exe。
    "--paths", (Split-Path $PSScriptRoot -Parent),
    "--add-data", "$(Split-Path $PSScriptRoot -Parent)\desk_hub\static;desk_hub\static",
    "--hidden-import", "desk_hub.server",
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.http.h11_impl",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.protocols.websockets.websockets_impl",
    "--hidden-import", "uvicorn.lifespan.on",
    "--add-data", "$configExample;.",
    "--add-data", "$petDir;attendance_helper\pet",
    "--collect-data", "certifi",
    "--hidden-import", "attendance_helper",
    "--hidden-import", "attendance_helper.ssl_certs",
    "--hidden-import", "certifi",
    "--hidden-import", "attendance_helper.ui.tray_app",
    "--hidden-import", "attendance_helper.ui.detail_popup",
    "--hidden-import", "attendance_helper.ui.settings_dialog",
    "--hidden-import", "attendance_helper.ui.setup_wizard",
    "--hidden-import", "attendance_helper.ui.diagnostics_dialog",
    "--hidden-import", "attendance_helper.ui.stats_dialog",
    "--hidden-import", "attendance_helper.remind_logic",
    "--hidden-import", "attendance_helper.display_strategy",
    "--hidden-import", "attendance_helper.ui.chat_dialog",
    "--hidden-import", "attendance_helper.ui.chat.dialog",
    "--hidden-import", "attendance_helper.ui.items_dialog",
    "--hidden-import", "attendance_helper.ui.reminder_toast",
    "--hidden-import", "attendance_helper.fun_copy",
    "--hidden-import", "attendance_helper.ai_client",
    "--hidden-import", "attendance_helper.ai_agent",
    "--hidden-import", "attendance_helper.activity_classify",
    "--hidden-import", "attendance_helper.activity_capture",
    "--hidden-import", "attendance_helper.activity_store",
    "--hidden-import", "attendance_helper.activity_tracker",
    "--hidden-import", "attendance_helper.ui.activity_dialog",
    "--hidden-import", "comtypes",
    "--hidden-import", "comtypes.client",
    "--hidden-import", "comtypes.gen.UIAutomationClient",
    "--collect-submodules", "comtypes.gen",
    # 新设备滑块验证要嵌入网页，不能再排除 WebEngine。
    "--hidden-import", "PySide6.QtWebChannel",
    "--hidden-import", "PySide6.QtWebEngineCore",
    "--hidden-import", "PySide6.QtWebEngineWidgets",
    "--exclude-module", "PySide6.QtWebEngineQuick",
    "--exclude-module", "PySide6.Qt3DCore",
    "--exclude-module", "PySide6.Qt3DRender",
    "--exclude-module", "PySide6.QtBluetooth",
    "--exclude-module", "PySide6.QtMultimedia",
    "--exclude-module", "PySide6.QtPdf",
    $entry
)

$buildOnefile = -not $OnedirOnly
$buildOnedir = -not $OnefileOnly
if ($OnefileOnly -and $OnedirOnly) {
    $buildOnefile = $true
    $buildOnedir = $true
}

function Write-UserReadme {
    param([string]$Path)
    @(
        "AttendanceHelper - Quick Start",
        "==============================",
        "",
        "1. Double-click AttendanceHelper.exe",
        "2. Fill Token + attendance Device ID + door Device ID",
        "3. Keep 'Start with Windows' checked",
        "4. Click Finish",
        "",
        "Tray:",
        "- Left click    = progress detail",
        "- Double-click  = open door",
        "- Right click   = menu (open door / refresh / stats / settings / exit)",
        "",
        "Keep the exe in a fixed folder. Config files (.env, config.json)",
        "are created next to the exe."
    ) | Set-Content -Path $Path -Encoding UTF8
}

if ($buildOnefile) {
    Write-Host "==> Building onefile exe (please wait) ..."
    & $venvPython -m PyInstaller --clean --onefile @commonArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Error "PyInstaller onefile failed"
        exit 1
    }
}

if ($buildOnedir) {
    Write-Host "==> Building onedir package for IT (faster cold start) ..."
    if ($buildOnefile) {
        & $venvPython -m PyInstaller --onedir @commonArgs
    } else {
        & $venvPython -m PyInstaller --clean --onedir @commonArgs
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "PyInstaller onedir failed"
        exit 1
    }
    $dirReadmeSrc = Join-Path $PSScriptRoot "README_IT.txt"
    $dirReadme = Join-Path $dist "AttendanceHelper\README_IT.txt"
    if (Test-Path $dirReadmeSrc) {
        Copy-Item -Force $dirReadmeSrc $dirReadme
    }
}

# 单文件运行时 Temp\_MEI* 可能被清理，exe 旁留一份 cacert.pem 作回退
$cacertSrc = Join-Path $PSScriptRoot ".venv\Lib\site-packages\certifi\cacert.pem"
if (Test-Path $cacertSrc) {
    if ($buildOnefile) {
        Copy-Item -Force $cacertSrc (Join-Path $dist "cacert.pem")
    }
    if ($buildOnedir) {
        Copy-Item -Force $cacertSrc (Join-Path $dist "AttendanceHelper\cacert.pem")
    }
} else {
    Write-Host "WARN: certifi cacert.pem not found, HTTPS may fail after Temp cleanup"
}

$readme = Join-Path $dist "README_FOR_USERS.txt"
Write-UserReadme -Path $readme

Write-Host ""
Write-Host "DONE"
if ($buildOnefile) {
    Write-Host "  ONEFILE : $(Join-Path $dist 'AttendanceHelper.exe')"
}
if ($buildOnedir) {
    Write-Host "  ONEDIR  : $(Join-Path $dist 'AttendanceHelper\AttendanceHelper.exe')"
}
Write-Host "  TIP     : $readme"
Write-Host "Share dist\AttendanceHelper.exe with colleagues; give IT the AttendanceHelper folder."
