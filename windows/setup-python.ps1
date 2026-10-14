# Puts a private Python, with the Windows audio package, inside this folder.
param(
    [Parameter(Mandatory = $true)][string]$Root
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = (Resolve-Path $Root).Path
$pyDir = Join-Path $Root "python"
$python = Join-Path $pyDir "python.exe"
$req = Join-Path $Root "requirements-windows.txt"
$pyVer = "3.12.10"

function Test-AudioModule([string]$Exe) {
    & $Exe -c "import pyaudiowpatch" 2>$null
    return $LASTEXITCODE -eq 0
}

if (Test-Path $python) {
    if (Test-AudioModule $python) { exit 0 }
} else {
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($arch -eq "AMD64") { $tag = "amd64" }
    elseif ($arch -eq "ARM64") { $tag = "arm64" }
    else { throw "32-bit Windows is not supported. Use 64-bit Windows." }

    New-Item -ItemType Directory -Force -Path $pyDir | Out-Null
    $zip = Join-Path $Root "python-embed.zip"
    $url = "https://www.python.org/ftp/python/$pyVer/python-$pyVer-embed-$tag.zip"
    Write-Host "Downloading Python $pyVer ($tag) into this folder..."
    Invoke-WebRequest -Uri $url -OutFile $zip
    tar -xf $zip -C $pyDir
    Remove-Item $zip -Force

    $pth = Get-ChildItem (Join-Path $pyDir "python*._pth") | Select-Object -First 1
    if (-not $pth) { throw "Embedded Python did not include a ._pth file." }
    $text = [IO.File]::ReadAllText($pth.FullName)
    $text = $text -replace "#import site", "import site"
    if ($text -notmatch "site-packages") {
        $text = $text.TrimEnd() + "`r`nLib\site-packages`r`n"
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [IO.File]::WriteAllText($pth.FullName, $text, $utf8)

    $getPip = Join-Path $pyDir "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
    & $python $getPip --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw "pip install failed." }
    Remove-Item $getPip -Force
}

Write-Host "Installing Windows audio support into .\python ..."
& $python -m pip install --disable-pip-version-check --no-warn-script-location -r $req
if ($LASTEXITCODE -ne 0) { throw "Could not install pyaudiowpatch." }
if (-not (Test-AudioModule $python)) { throw "pyaudiowpatch did not import." }
Write-Host "Python is ready in .\python"
exit 0
