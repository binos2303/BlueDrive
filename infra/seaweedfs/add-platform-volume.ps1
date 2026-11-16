#requires -version 5.1
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^volume([4-9]|1[0-2])$')]
    [string]$NodeName,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Compose = Join-Path $PSScriptRoot 'compose.yml'
$Local = Join-Path $PSScriptRoot '.local'
$RegistryPath = Join-Path $Local 'platform-nodes.json'
$OverridePath = Join-Path $Local 'platform-nodes.compose.yml'
$NodePattern = '^volume([4-9]|1[0-2])$'

# Registry là danh sách node lab đã triển khai; không được nhận tên/địa chỉ tùy ý.
$Existing = @()
if (Test-Path -LiteralPath $RegistryPath -PathType Leaf) {
    $Registry = Get-Content -LiteralPath $RegistryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($Node in @($Registry.extra_nodes)) {
        if ([string]$Node -notmatch $NodePattern) { throw 'Unsafe node name in local registry.' }
        $Existing += [string]$Node
    }
}
$Names = @($Existing + $NodeName | Sort-Object -Unique)
$Names = @($Names | Sort-Object { [int]($_ -replace '^volume', '') })
$NetworkName = 'bluedrive-seaweedfs_storage'
if (-not $Apply) {
    Write-Host ('PREVIEW: add {0} to Platform lab. Existing extras: {1}' -f $NodeName, ($Existing -join ', '))
    Write-Host 'This does not change the database or Platform Storage Binding.'
    Write-Host ('Use: & .\infra\seaweedfs\add-platform-volume.ps1 -NodeName {0} -Apply' -f $NodeName)
    return
}
if ($Existing -contains $NodeName) {
    throw "Node $NodeName is already in the Platform node registry. Use Refresh to check its status."
}
if (-not (Test-Path -LiteralPath $Local -PathType Container)) {
    throw 'SeaweedFS .local directory missing. Configure the Platform lab first.'
}
# Không cho triển khai node nếu cluster hiện tại chưa phản hồi.
$Master = Invoke-RestMethod -Uri 'http://127.0.0.1:9333/dir/status' -TimeoutSec 5
if (-not $Master.Topology) { throw 'SeaweedFS Master topology unavailable.' }

# Compose override nằm trong .local, có volume dữ liệu độc lập cho từng node.
$Lines = [System.Collections.Generic.List[string]]::new()
$Lines.Add('services:')
foreach ($Name in $Names) {
    $Lines.Add(('  {0}:' -f $Name))
    $Lines.Add('    image: chrislusf/seaweedfs:4.53')
    $Lines.Add('    restart: unless-stopped')
    $Lines.Add('    networks: [storage]')
    $Lines.Add(('    command: [volume, -ip={0}, -ip.bind=0.0.0.0, -port=8080, -master=master:9333, -dir=/data, -max=32, -dataCenter=platform, -rack=lab]' -f $Name))
    $Lines.Add(('    volumes: [{0}_data:/data]' -f $Name))
    $Lines.Add('    depends_on:')
    $Lines.Add('      master: {condition: service_healthy}')
    $Lines.Add('    healthcheck:')
    $Lines.Add('      test: [CMD, curl, -fsS, http://localhost:8080/status]')
    $Lines.Add('      interval: 10s')
    $Lines.Add('      timeout: 5s')
    $Lines.Add('      retries: 12')
}
$Lines.Add('volumes:')
foreach ($Name in $Names) { $Lines.Add(('  {0}_data:' -f $Name)) }
$Encoder = New-Object System.Text.UTF8Encoding($false)
$TempOverride = Join-Path $Local ('platform-nodes.compose.' + [guid]::NewGuid().ToString('N') + '.yml')
[System.IO.File]::WriteAllLines($TempOverride, [string[]]$Lines, $Encoder)
Push-Location $Repo
try {
    docker compose -f $Compose -f $TempOverride config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Generated node Compose configuration is invalid.' }

    # Replace only the generated local override; never modify the original Compose or volumes.
    Copy-Item -LiteralPath $TempOverride -Destination $OverridePath -Force
    docker compose -f $Compose -f $OverridePath up --no-deps -d --wait $NodeName
    if ($LASTEXITCODE -ne 0) { throw 'New Volume Server failed to become healthy.' }

    $Registered = $false
    for ($Attempt = 0; $Attempt -lt 15; $Attempt++) {
        $Response = Invoke-RestMethod -Uri 'http://127.0.0.1:9333/dir/status' -TimeoutSec 5
        $Ids = @($Response.Topology.DataCenters | ForEach-Object { $_.Racks } | ForEach-Object { $_.DataNodes } | ForEach-Object { ([string]$_.Url).Split(':')[0] })
        if ($Ids -contains $NodeName) { $Registered = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $Registered) { throw "Container started but Master did not register $NodeName; local registry unchanged." }
    $Data = @{ extra_nodes = @($Names) } | ConvertTo-Json -Depth 4
    $TempRegistry = Join-Path $Local ('platform-nodes.' + [guid]::NewGuid().ToString('N') + '.json')
    [System.IO.File]::WriteAllText($TempRegistry, $Data, $Encoder)
    Move-Item -LiteralPath $TempRegistry -Destination $RegistryPath -Force
    Write-Host "NODE REGISTERED: $NodeName. Open Storage Dashboard and click Refresh." -ForegroundColor Green
    Write-Host 'The node has its own persistent Docker volume. No data migration or balancing was performed.'
} finally {
    Pop-Location
    if (Test-Path -LiteralPath $TempOverride) { Remove-Item -LiteralPath $TempOverride -Force }
}
