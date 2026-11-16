param([switch]$InstallDependencies)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot '.python'
$packagePath = Join-Path $runtimeRoot 'python.3.12.10.nupkg'
$packageHash = '0EB85C2DFCCCCF1B17352DE4C397F69194035B7D37149EACC16F1147D93DE3B8'
$pythonRoot = Join-Path $runtimeRoot 'cpython-3.12.10'
$basePython = Join-Path $pythonRoot 'tools\python.exe'
$venvRoot = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'

# Dùng runtime trong dự án, không sửa PATH, registry hoặc Python của ứng dụng khác.
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $basePython)) {
    if (-not (Test-Path -LiteralPath $packagePath)) {
        Invoke-WebRequest -UseBasicParsing -Uri 'https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg' -OutFile $packagePath
    }
    if ((Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash -ne $packageHash) {
        throw 'CPython package hash mismatch. Giữ file để kiểm tra; không giải nén hoặc chạy.'
    }
    if (Test-Path -LiteralPath $pythonRoot) {
        throw 'Runtime chưa hoàn tất đã tồn tại; kiểm tra riêng, không ghi đè hoặc xóa tự động.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($packagePath, $pythonRoot)
}
& $basePython -I -c 'import sys, venv; assert sys.version_info[:3] == (3, 12, 10)'
if ($LASTEXITCODE -ne 0) { throw 'CPython runtime/version không hợp lệ.' }

$venvHealthy = $false
if (Test-Path -LiteralPath $venvPython) {
    try {
        & $venvPython -I -c 'import sys; from pathlib import Path; assert sys.version_info[:3] == (3, 12, 10); assert sys.prefix != sys.base_prefix; assert Path(sys.base_prefix).resolve() == Path(sys.argv[1]).resolve()' (Join-Path $pythonRoot 'tools') 2>$null
        $venvHealthy = $LASTEXITCODE -eq 0
    } catch { $venvHealthy = $false }
}
if (-not $venvHealthy) {
    if (Test-Path -LiteralPath $venvRoot) {
        # Chỉ thay launcher/config, giữ nguyên site-packages và bản config cũ để đối chiếu.
        $previousConfig = Join-Path $venvRoot 'pyvenv.cfg'
        $savedConfig = Join-Path $runtimeRoot 'pyvenv.before-repair.cfg'
        if ((Test-Path -LiteralPath $previousConfig) -and -not (Test-Path -LiteralPath $savedConfig)) {
            Copy-Item -LiteralPath $previousConfig -Destination $savedConfig
        }
        & $basePython -I -m venv --upgrade --without-pip $venvRoot
    } else {
        & $basePython -I -m venv $venvRoot
    }
    if ($LASTEXITCODE -ne 0) { throw 'Không thể khôi phục .venv; không xóa môi trường cũ.' }
}
if ($InstallDependencies) {
    & $venvPython -I -m pip --require-virtualenv install -r (Join-Path $projectRoot 'backend\requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Không thể cài dependencies đã ghim.' }
}
& $venvPython -I -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency compatibility check thất bại.' }
Write-Output 'PASS: project CPython 3.12.10, single .venv, dependency compatibility.'
