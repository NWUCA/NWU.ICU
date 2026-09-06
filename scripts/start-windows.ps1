param(
    [switch]$SkipFrontend
)

$ErrorActionPreference = 'Stop'

$backendRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $backendRoot
$frontendRoot = Join-Path $workspaceRoot 'new_nwu_icu_frontend'
$backendEnv = Join-Path $backendRoot '.env.windows'
$frontendEnv = Join-Path $frontendRoot '.env.windows.local'

if (-not (Test-Path -LiteralPath $backendEnv)) {
    $existingEnv = Join-Path $backendRoot '.env'
    if (Test-Path -LiteralPath $existingEnv) {
        Copy-Item -LiteralPath $existingEnv -Destination $backendEnv
        Write-Host 'Created NWU.ICU/.env.windows from the existing environment to preserve database credentials and mounts.'
    }
    else {
        Copy-Item -LiteralPath (Join-Path $backendRoot '.env.windows.example') -Destination $backendEnv
        Write-Host 'Created NWU.ICU/.env.windows from the safe local template.'
    }
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $pattern = '^' + [regex]::Escape($Name) + '='
    $found = $false
    $updatedLines = foreach ($line in (Get-Content -LiteralPath $Path)) {
        if ($line -match $pattern) {
            $found = $true
            "$Name=$Value"
        }
        else {
            $line
        }
    }
    if (-not $found) {
        $updatedLines += "$Name=$Value"
    }
    [System.IO.File]::WriteAllLines(
        $Path,
        [string[]]$updatedLines,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Set-EnvDefault {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $pattern = '^' + [regex]::Escape($Name) + '='
    if (-not (Select-String -LiteralPath $Path -Pattern $pattern -Quiet)) {
        Set-EnvValue -Path $Path -Name $Name -Value $Value
    }
}

Set-EnvValue -Path $backendEnv -Name 'ENV_FILE' -Value '.env.windows'
Set-EnvValue -Path $backendEnv -Name 'DEBUG' -Value 'True'
Set-EnvValue -Path $backendEnv -Name 'DISABLE_FILE_UPLOAD_CHMOD' -Value 'True'
Set-EnvValue -Path $backendEnv -Name 'SECURE_SSL_REDIRECT' -Value 'False'
Set-EnvValue -Path $backendEnv -Name 'TRUST_X_FORWARDED_PROTO' -Value 'False'
Set-EnvValue -Path $backendEnv -Name 'SECURE_HSTS_SECONDS' -Value '0'
Set-EnvValue -Path $backendEnv -Name 'FRONTEND_URL' -Value 'http://localhost:5173'
Set-EnvValue -Path $backendEnv -Name 'CSRF_TRUSTED_ORIGINS' -Value 'http://localhost:5173,http://127.0.0.1:5173'
Set-EnvDefault -Path $backendEnv -Name 'DB_HOST' -Value 'db'
Set-EnvDefault -Path $backendEnv -Name 'DB_PORT' -Value '5432'
Set-EnvDefault -Path $backendEnv -Name 'MEDIA_STORAGE_HOST_PATH' -Value './media'
Set-EnvDefault -Path $backendEnv -Name 'RESOURCE_INDEX_HOST_PATH' -Value './data'
Set-EnvDefault -Path $backendEnv -Name 'RESOURCE_STORAGE_HOST_PATH' -Value './resource-storage'
Set-EnvDefault -Path $backendEnv -Name 'RESOURCE_STORAGE_ROOT' -Value '/resource-storage'

if (-not (Test-Path -LiteralPath $frontendRoot)) {
    throw "Frontend repository not found at $frontendRoot"
}

if (-not (Test-Path -LiteralPath $frontendEnv)) {
    Copy-Item -LiteralPath (Join-Path $frontendRoot '.env.windows.example') -Destination $frontendEnv
    Write-Host 'Created new_nwu_icu_frontend/.env.windows.local.'
}

New-Item -ItemType Directory -Force -Path (Join-Path $backendRoot 'media') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $backendRoot 'data') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $backendRoot 'resource-storage') | Out-Null

Push-Location $backendRoot
try {
    $env:ENV_FILE = '.env.windows'
    docker compose --env-file .env.windows -f docker-compose.yaml up --build -d
    if ($LASTEXITCODE -ne 0) { throw 'Backend Docker Compose startup failed.' }
}
finally {
    Remove-Item Env:ENV_FILE -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host 'Backend is running at http://127.0.0.1:8000.'

if (-not $SkipFrontend) {
    Push-Location $frontendRoot
    try {
        corepack pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        Write-Host 'Starting Vite at http://localhost:5173. Press Ctrl+C to stop Vite.'
        corepack pnpm dev --mode windows
    }
    finally {
        Pop-Location
    }
}
