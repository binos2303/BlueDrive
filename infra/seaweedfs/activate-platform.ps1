#requires -version 5.1
param(
    [switch]$Apply,
    [string]$Operator = "bluedrive_admin"
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Compose = Join-Path $PSScriptRoot "compose.yml"
$BackendEnv = Join-Path $Repo "backend\.env"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python venv not found." }
if (-not (Test-Path -LiteralPath $BackendEnv -PathType Leaf)) { throw "backend/.env not found." }
Push-Location $Repo
try {
    docker compose -f $Compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Invalid SeaweedFS Compose configuration." }

    # Kiểm tra trạng thái Revision/role mà không tạo Binding.
    & $Python -X utf8 .\backend\manage.py prepare_platform_storage --operator $Operator
    if ($LASTEXITCODE -ne 0) { throw "Verified Platform revision or operator unavailable." }
    if (-not $Apply) {
        Write-Host "PREVIEW ONLY: compose validated. Use -Apply to deploy 3 nodes, bind verified storage and enable routing."
        return
    }

    docker compose -f $Compose up -d --wait
    if ($LASTEXITCODE -ne 0) { throw "SeaweedFS services failed to reach healthy state." }

    $Names = @("volume", "volume2", "volume3")
    $Seen = @()
    for ($attempt = 0; $attempt -lt 6; $attempt++) {
        try {
            $Data = Invoke-RestMethod -Uri "http://127.0.0.1:9333/dir/status" -TimeoutSec 5
            $Seen = @()
            foreach ($dc in @($Data.Topology.DataCenters)) {
                foreach ($rack in @($dc.Racks)) {
                    foreach ($node in @($rack.DataNodes)) {
                        $Name = ([string]$node.Url).Split(':')[0]
                        if ($Names -contains $Name) { $Seen += $Name }
                    }
                }
            }
            if (@($Seen | Sort-Object -Unique).Count -eq 3) { break }
        } catch { $Seen = @() }
        Start-Sleep -Seconds 2
    }
    $Missing = @($Names | Where-Object { $Seen -notcontains $_ })
    if ($Missing.Count -gt 0) { throw "Master does not list all 3 volume nodes: $($Missing -join ', '). Routing unchanged." }

    & $Python -X utf8 .\backend\manage.py prepare_platform_storage --operator $Operator --apply
    if ($LASTEXITCODE -ne 0) { throw "Verified Platform binding failed. Routing unchanged." }

    # Chỉ đổi cờ sau khi node đã đăng ký và Binding đã được tạo hợp lệ.
    # Sao lưu .env (có secrets) trong Downloads; KHÔNG gửi hoặc commit file này.
    $Backup = Join-Path $env:USERPROFILE ("Downloads\BLUEDRIVE_BACKEND_ENV_BEFORE_ROUTING_{0}.bak" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    Copy-Item -LiteralPath $BackendEnv -Destination $Backup -ErrorAction Stop
    $Content = @(Get-Content -LiteralPath $BackendEnv -Encoding UTF8)
    $Key = 'SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED'
    $Pattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    $Count = @($Content | Where-Object { $_ -match $Pattern }).Count
    if ($Count -gt 1) { throw "Duplicate routing keys in backend/.env. Manual review required." }
    if ($Count -eq 1) {
        $Content = @($Content | ForEach-Object { if ($_ -match $Pattern) { "$Key=true" } else { $_ } })
    } else {
        $Content += "$Key=true"
    }
    # PowerShell 5.1 Set-Content -Encoding UTF8 thêm BOM có thể làm hỏng key đầu .env.
    [System.IO.File]::WriteAllLines($BackendEnv, [string[]]$Content, (New-Object System.Text.UTF8Encoding($false)))

    & $Python -X utf8 .\backend\manage.py check
    if ($LASTEXITCODE -ne 0) { throw "Django system check failed; use .env backup to revert routing." }
    Write-Host "PLATFORM STORAGE PREPARED: 3 volume servers registered, verified binding active, routing flag enabled." -ForegroundColor Green
    Write-Host "Restart Django API and Finalizer to load updated routing flag; verify My Drive and Personal Workspace upload/download." -ForegroundColor Yellow
    Write-Host "Backend .env backup created in Downloads (contains secrets; do not share)."
} finally {
    Pop-Location
}
