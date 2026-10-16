$ErrorActionPreference = 'Stop'

# SecureDrive local development launcher for Windows PowerShell.
# Adjust these paths if your project or MinIO installation is stored elsewhere.
$ProjectRoot = 'C:\Users\dang2\Project\SecureDrive'
$BackendDir = Join-Path $ProjectRoot 'backend'
$FrontendDir = Join-Path $ProjectRoot 'frontend'
$VenvPython = Join-Path $BackendDir 'venv\Scripts\python.exe'
$MinioDataDir = 'C:\minio\data'

function Start-PowerShellWindow {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$Command
    )
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit', '-EncodedCommand', $encoded) | Out-Null
    Write-Host "Started terminal: $Title" -ForegroundColor Green
}

foreach ($requiredPath in @($ProjectRoot, $BackendDir, $FrontendDir, $VenvPython)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path not found: $requiredPath`nEdit the path variables at the top of start-securedrive.ps1."
    }
}

# Try to start PostgreSQL automatically only when exactly one PostgreSQL service is installed.
$pgServices = @(Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'postgresql*' })
$runningPg = @($pgServices | Where-Object { $_.Status -eq 'Running' })
if ($runningPg.Count -gt 0) {
    Write-Host ("PostgreSQL already running: " + (($runningPg | ForEach-Object Name) -join ', ')) -ForegroundColor Green
} elseif ($pgServices.Count -eq 1) {
    try {
        Start-Service -Name $pgServices[0].Name
        Write-Host "Started PostgreSQL service: $($pgServices[0].Name)" -ForegroundColor Green
    } catch {
        Write-Warning "Could not start PostgreSQL automatically. Start service '$($pgServices[0].Name)' manually (may require Administrator rights)."
    }
} elseif ($pgServices.Count -gt 1) {
    Write-Warning 'Multiple PostgreSQL services are installed and none is running. Start the intended PostgreSQL service manually.'
} else {
    Write-Warning 'No PostgreSQL Windows service was found. Ensure PostgreSQL is running before using SecureDrive.'
}

# Start MinIO only if nothing is listening on its usual S3 API port.
$minioListener = @(Get-NetTCPConnection -LocalPort 9000 -State Listen -ErrorAction SilentlyContinue)
if ($minioListener.Count -gt 0) {
    Write-Host 'Port 9000 already has a listener; assuming MinIO (or the configured S3 service) is already running.' -ForegroundColor Green
} else {
    $MinioExe = Join-Path $PSScriptRoot 'minio.exe'
    if (-not (Test-Path -LiteralPath $MinioExe)) { $MinioExe = 'C:\minio\minio.exe' }
    if (-not (Test-Path -LiteralPath $MinioExe)) {
        $MinioExe = Read-Host 'Enter the full path to minio.exe (example: C:\tools\minio.exe)'
    }
    if (-not (Test-Path -LiteralPath $MinioExe)) {
        throw "minio.exe was not found: $MinioExe. Edit the script or enter the correct path when prompted."
    }
    if (-not (Test-Path -LiteralPath $MinioDataDir)) {
        New-Item -ItemType Directory -Path $MinioDataDir -Force | Out-Null
    }
    $MinioExeEscaped = $MinioExe.Replace("'", "''")
    $MinioDir = (Split-Path -Parent $MinioExe).Replace("'", "''")
    $MinioDataEscaped = $MinioDataDir.Replace("'", "''")
    $minioCommand = "Set-Location -LiteralPath '$MinioDir'; & '$MinioExeEscaped' server '$MinioDataEscaped' --console-address ':9001'"
    Start-PowerShellWindow -Title 'MinIO' -Command $minioCommand
    Start-Sleep -Seconds 2
}

$BackendEscaped = $BackendDir.Replace("'", "''")
$PythonEscaped = $VenvPython.Replace("'", "''")
$backendCommand = "Set-Location -LiteralPath '$BackendEscaped'; & '$PythonEscaped' manage.py runserver"
$finalizerCommand = "Set-Location -LiteralPath '$BackendEscaped'; & '$PythonEscaped' manage.py run_upload_finalizer"
$FrontendEscaped = $FrontendDir.Replace("'", "''")
$frontendCommand = "Set-Location -LiteralPath '$FrontendEscaped'; npm run dev"

Start-PowerShellWindow -Title 'SecureDrive Django API' -Command $backendCommand
Start-PowerShellWindow -Title 'SecureDrive Upload Finalizer' -Command $finalizerCommand
Start-PowerShellWindow -Title 'SecureDrive Next.js' -Command $frontendCommand

Write-Host ''
Write-Host 'SecureDrive startup commands were launched in separate terminals.' -ForegroundColor Cyan
Write-Host 'Frontend:       http://localhost:3000' -ForegroundColor Cyan
Write-Host 'MinIO Console:  http://localhost:9001 (when MinIO is running)' -ForegroundColor Cyan
Write-Host 'Django API:     http://127.0.0.1:8000' -ForegroundColor Cyan
Write-Host 'Keep the terminal windows open while using the project.' -ForegroundColor Yellow
