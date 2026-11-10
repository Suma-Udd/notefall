# NoteFall installer for Windows.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/Suma-Udd/notefall/main/scripts/install.ps1 | iex"
#
# Installs uv (a tiny Python manager, it brings its own Python so you don't
# need one), installs NoteFall with it, and puts a NoteFall shortcut on your
# desktop and in the Start menu. No admin rights needed. Run it again to update.

$ErrorActionPreference = "Stop"
$Source = if ($env:NOTEFALL_SOURCE) { $env:NOTEFALL_SOURCE } else { "notefall @ https://github.com/Suma-Udd/notefall/archive/refs/heads/main.zip" }

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Green }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Say "Getting uv (installs Python for NoteFall, nothing system wide)"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Say "Installing NoteFall"
uv tool install --force --python 3.12 "$Source"
if ($LASTEXITCODE -ne 0) { throw "uv couldn't install NoteFall" }

$BinDir = (uv tool dir --bin).Trim()
$ToolDir = (uv tool dir).Trim()
$App = Join-Path $BinDir "notefall-app.exe"
$IconBase = Join-Path $ToolDir "notefall\notefall-icon"
& (Join-Path $ToolDir "notefall\Scripts\python.exe") -c "from notefall.icon import save_icons; save_icons(r'$IconBase')"

Say "Adding shortcuts"
$Shell = New-Object -ComObject WScript.Shell
$Targets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "NoteFall.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "NoteFall.lnk")
)
foreach ($t in $Targets) {
    $lnk = $Shell.CreateShortcut($t)
    $lnk.TargetPath = $App
    $lnk.IconLocation = "$IconBase.ico"
    $lnk.Description = "Turn piano music into a falling notes video"
    $lnk.Save()
}

Say "Done! Double-click NoteFall on your desktop."
