#Requires -Version 5.1
# Installed by install-campus-login.ps1 and run as SYSTEM by Task Scheduler.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$logPath = Join-Path $PSScriptRoot 'campus-login.log'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$env:PYTHONIOENCODING = 'utf-8'

function Write-Log([string] $Message) {
    if ([IO.File]::Exists($logPath) -and ([IO.FileInfo]::new($logPath)).Length -ge 5MB) {
        Move-Item -LiteralPath $logPath -Destination "$logPath.1" -Force
    }
    $line = '{0} {1}{2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message, [Environment]::NewLine
    [IO.File]::AppendAllText($logPath, $line, $utf8)
}

try {
    $config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $credentialPath = Join-Path $PSScriptRoot 'credentials.json'
    $loginArguments = @('--watch', $config.network, '-i', $config.interface, '--cred', $credentialPath)
    if ($config.PSObject.Properties['executable']) {
        $loginCommand = $config.executable
        $requiredPaths = @($loginCommand, $credentialPath)
    } else {
        $loginCommand = $config.python
        $loginScript = Join-Path $PSScriptRoot 'campus-login.py'
        $requiredPaths = @($loginCommand, $loginScript, $credentialPath)
        $loginArguments = @('-u', $loginScript) + $loginArguments
    }
    foreach ($path in $requiredPaths) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required file is missing: $path"
        }
    }
    while ($true) {
        # Native stderr must be logged without terminating the supervisor in
        # Windows PowerShell 5.1. Preserve argv boundaries (including spaces).
        $ErrorActionPreference = 'Continue'
        & $loginCommand @loginArguments 2>&1 | ForEach-Object { Write-Log $_.ToString() }
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        Write-Log "Login process exited with code $exitCode; restarting in 10 seconds."
        Start-Sleep -Seconds 10
    }
} catch {
    $ErrorActionPreference = 'Stop'
    Write-Log "Supervisor failed: $($_.Exception.Message)"
    exit 1
}
