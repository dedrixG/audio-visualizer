# Start Menu, Desktop, and Settings > Apps entry. Files stay in -Root.
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [ValidateSet("Install", "Uninstall")][string]$Action = "Install"
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path.TrimEnd("\")
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AudioVisualizer"
$shell = New-Object -ComObject WScript.Shell

function Get-ShortcutPath([string]$Place) {
    $folder = if ($Place -eq "Desktop") {
        [Environment]::GetFolderPath("Desktop")
    } else {
        [Environment]::GetFolderPath("Programs")
    }
    return (Join-Path $folder "Audio Visualizer.lnk")
}

if ($Action -eq "Uninstall") {
    foreach ($place in @("Desktop", "Programs")) {
        $path = Get-ShortcutPath $place
        if (Test-Path $path) { Remove-Item $path -Force }
    }
    if (Test-Path $key) { Remove-Item $key -Recurse -Force }
    & netsh advfirewall firewall delete rule name="Audio Visualizer" | Out-Null
    exit 0
}

$target = Join-Path $Root "start.bat"
foreach ($place in @("Desktop", "Programs")) {
    $link = $shell.CreateShortcut((Get-ShortcutPath $place))
    $link.TargetPath = $target
    $link.WorkingDirectory = $Root
    $link.WindowStyle = 1
    $link.Description = "System audio visualizer"
    $link.Save()
}

New-Item -Path $key -Force | Out-Null
Set-ItemProperty -Path $key -Name DisplayName -Value "Audio Visualizer"
Set-ItemProperty -Path $key -Name Publisher -Value "dedrixG"
Set-ItemProperty -Path $key -Name DisplayVersion -Value "1.0.1"
Set-ItemProperty -Path $key -Name InstallLocation -Value $Root
Set-ItemProperty -Path $key -Name UninstallString -Value "`"$(Join-Path $Root 'uninstall.bat')`""
New-ItemProperty -Path $key -Name NoModify -PropertyType DWord -Value 1 -Force | Out-Null
New-ItemProperty -Path $key -Name NoRepair -PropertyType DWord -Value 1 -Force | Out-Null

$fw = & netsh advfirewall firewall add rule name="Audio Visualizer" dir=in action=allow protocol=TCP localport=8765 profile=private,domain
if ($LASTEXITCODE -ne 0) {
    Write-Host "Firewall rule was not added. A phone on Wi-Fi may need that rule from an Administrator window."
}
exit 0
