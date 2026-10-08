#Requires -Version 5.1
<#
.SYNOPSIS
Installs campus auto-login as a quiet Windows startup task.
.DESCRIPTION
Requires a Windows-compatible campus-login.py with the original --watch,
-i and --cred command-line options, and a machine-wide Python 3 installation.
Run from an elevated PowerShell prompt. Use -WhatIf to preview or -Uninstall
to remove the task (installed files and credentials are retained).
.EXAMPLE
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-campus-login.ps1
.EXAMPLE
.\install-campus-login.ps1 -CredentialPath .\credentials.json -Interface 'Wi-Fi'
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Position = 0)]
    [string] $CredentialPath = (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.campus-login'),
    [string] $LoginScript,
    [ValidateNotNullOrEmpty()]
    [string] $Network = $(if ($env:CAMPUS_NETWORK) { $env:CAMPUS_NETWORK } else { 'Tsinglan-School' }),
    [string] $Interface = $env:CAMPUS_IFACE,
    [string] $PythonPath,
    [switch] $NoStart,
    [switch] $Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskName = 'CampusLogin'
$installDir = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'CampusLogin'
$installedCredential = Join-Path $installDir 'credentials.json'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this installer from PowerShell opened with Run as administrator.'
    }
}

function Set-PrivatePath([string] $Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to install through a junction or symbolic link: $Path"
    }
    $systemSid = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
    $adminSid = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
    if ($item.PSIsContainer) {
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $inheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    } else {
        $acl = New-Object Security.AccessControl.FileSecurity
        $inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($adminSid)
    foreach ($sid in @($systemSid, $adminSid)) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $sid, [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance, [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

if ($Uninstall) {
    if ($PSCmdlet.ShouldProcess($taskName, 'Stop and unregister the campus login task')) {
        Assert-Administrator
        $existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
        if ($existing) {
            Stop-ScheduledTask -TaskName $taskName -TaskPath '\'
            Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false
        }
        Write-Host "Task removed. Installed files and credentials remain in $installDir."
    }
    return
}

# Validate dependencies before changing files or an existing task.
if (-not $LoginScript) {
    $LoginScript = Join-Path $PSScriptRoot 'campus-login.py'
}
if (-not (Test-Path -LiteralPath $LoginScript -PathType Leaf)) {
    throw "Login script not found: $LoginScript. Supply a Windows-compatible campus-login.py with -LoginScript."
}
$LoginScript = (Resolve-Path -LiteralPath $LoginScript).ProviderPath
$runnerSource = Join-Path $PSScriptRoot 'run-campus-login.ps1'
if (-not (Test-Path -LiteralPath $runnerSource -PathType Leaf)) {
    throw "Runner not found: $runnerSource. Keep both PowerShell files together."
}
$windowsSource = Join-Path (Split-Path -Parent $LoginScript) 'campus_login_windows.py'
if (-not (Test-Path -LiteralPath $windowsSource -PathType Leaf)) {
    $windowsSource = Join-Path $PSScriptRoot 'campus_login_windows.py'
}
if (-not (Test-Path -LiteralPath $windowsSource -PathType Leaf)) {
    throw 'Windows support module not found. Keep campus_login_windows.py with the installer.'
}
if (-not (Test-Path -LiteralPath $CredentialPath -PathType Leaf)) {
    if (Test-Path -LiteralPath $installedCredential -PathType Leaf) {
        # Only reuse installed credentials when the default input was omitted.
        if (-not $PSBoundParameters.ContainsKey('CredentialPath')) {
            $CredentialPath = $installedCredential
        } else {
            throw "Credential file not found: $CredentialPath"
        }
    } else {
        throw "Credential file not found: $CredentialPath. Expected JSON with user and password fields."
    }
}
try {
    $credentialText = Get-Content -LiteralPath $CredentialPath -Raw -Encoding UTF8
    if (-not $credentialText.TrimStart().StartsWith('{')) {
        throw 'Credential JSON must be an object.'
    }
    $credential = $credentialText | ConvertFrom-Json
} catch {
    throw 'Cannot read credential JSON. Expected an object with user and password fields.'
}
foreach ($field in @('user', 'password')) {
    $property = $credential.PSObject.Properties[$field]
    if ($null -eq $property -or $property.Value -isnot [string] -or [string]::IsNullOrWhiteSpace($property.Value)) {
        throw "Credential JSON must contain a non-empty string field named $field."
    }
}
$credentialJson = @{ user = $credential.user; password = $credential.password } | ConvertTo-Json

if (-not $PythonPath) {
    # Get-Command can return several executables; never stringify their paths
    # together, and do not select a per-user install or the Store launcher.
    $pythonCommand = Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch '(?i)\\Users\\|\\WindowsApps\\' } |
        Select-Object -First 1
    if (-not $pythonCommand) {
        throw 'Machine-wide Python 3 not found. Install Python for all users or specify -PythonPath.'
    }
    $PythonPath = $pythonCommand.Source
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable not found: $PythonPath"
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).ProviderPath
if ($PythonPath -match '(?i)\\Users\\|\\WindowsApps\\') {
    throw 'The SYSTEM task needs machine-wide Python, not a per-user install or Microsoft Store alias. Specify -PythonPath to an all-users installation.'
}
$pythonInfo = & $PythonPath -I -c "import json, sys; print(json.dumps({'version': sys.version_info.major, 'executable': sys.executable}))"
if ($LASTEXITCODE -ne 0) {
    throw 'Could not start the selected Python executable.'
}
$pythonInfo = $pythonInfo | ConvertFrom-Json
if ($pythonInfo.version -ne 3) {
    throw 'Python 3 is required.'
}
$PythonPath = $pythonInfo.executable

if (-not $Interface) {
    $adapters = @(Get-NetAdapter -Physical | Where-Object {
        $_.NdisPhysicalMedium -in @(1, 9) -and $_.Status -ne 'Not Present'
    })
    $connectedAdapters = @($adapters | Where-Object { $_.Status -eq 'Up' })
    if ($connectedAdapters.Count -eq 1) {
        $adapters = $connectedAdapters
    }
    if ($adapters.Count -ne 1) {
        $candidates = ($adapters | ForEach-Object { '{0} [{1}]' -f $_.Name, $_.Status }) -join ', '
        if (-not $candidates) { $candidates = 'none' }
        throw "Could not select one Wi-Fi adapter. Candidates: $candidates. Use Get-NetAdapter, then specify -Interface with its Name."
    }
    $Interface = $adapters[0].Name
}
$configJson = @{
    python = $PythonPath
    network = $Network
    interface = $Interface
} | ConvertTo-Json

if (-not $PSCmdlet.ShouldProcess("$installDir and scheduled task $taskName", "Install auto-login for $Network on $Interface")) {
    return
}
Assert-Administrator
Import-Module ScheduledTasks

# Reject links before any writes. Only SYSTEM and administrators may change
# the code executed by SYSTEM or read the stored credential file.
if (Test-Path -LiteralPath $installDir) {
    Set-PrivatePath $installDir
} else {
    New-Item -ItemType Directory -Path $installDir | Out-Null
    Set-PrivatePath $installDir
}
foreach ($name in @('campus-login.py', 'campus_login_windows.py', 'run-campus-login.ps1', 'config.json', 'credentials.json', 'campus-login.log', 'campus-login.log.1')) {
    $destination = Join-Path $installDir $name
    if (Test-Path -LiteralPath $destination) {
        Set-PrivatePath $destination
    }
}
$existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $taskName -TaskPath '\'
}
foreach ($source in @($LoginScript, $windowsSource, $runnerSource)) {
    $destination = Join-Path $installDir ([IO.Path]::GetFileName($source))
    # -LoginScript may refer to a differently named file.
    if ($source -eq $LoginScript) { $destination = Join-Path $installDir 'campus-login.py' }
    if (-not [string]::Equals($source, $destination, [StringComparison]::OrdinalIgnoreCase)) {
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
    Set-PrivatePath $destination
}
[IO.File]::WriteAllText($installedCredential, $credentialJson, $utf8)
[IO.File]::WriteAllText((Join-Path $installDir 'config.json'), $configJson, $utf8)
Set-PrivatePath $installedCredential
Set-PrivatePath (Join-Path $installDir 'config.json')

$powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$runnerPath = Join-Path $installDir 'run-campus-login.ps1'
$action = New-ScheduledTaskAction -Execute $powershellPath -WorkingDirectory $installDir -Argument (
    '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $runnerPath
)
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -Priority 7
Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Description "Campus portal auto-login on $Network" -Force | Out-Null
if (-not $NoStart) {
    Start-ScheduledTask -TaskName $taskName -TaskPath '\'
}
Get-ScheduledTask -TaskName $taskName -TaskPath '\' | Select-Object TaskName, State
Write-Host "Logs: $installDir\campus-login.log"
