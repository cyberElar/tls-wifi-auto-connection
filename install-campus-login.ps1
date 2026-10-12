#Requires -Version 5.1
<#
.SYNOPSIS
Installs campus auto-login as a quiet Windows startup task.
.DESCRIPTION
Accepts a bundled worker with -LoginExecutable, or a Windows-compatible
campus-login.py and a machine-wide Python 3 installation for source installs.
The worker must support the original --watch, -i and --cred options.
Run from an elevated PowerShell prompt. Use -WhatIf to preview or -Uninstall
to remove the task; add -RemoveData to also delete the saved credentials, logs
and installed files.
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
    [string] $LoginExecutable,
    [ValidateNotNullOrEmpty()]
    [string] $Network = $(if ($env:CAMPUS_NETWORK) { $env:CAMPUS_NETWORK } else { 'Tsinglan-School' }),
    [string] $Interface = $env:CAMPUS_IFACE,
    [string] $PythonPath,
    [switch] $NoStart,
    [switch] $Uninstall,
    [switch] $RemoveData
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskName = 'CampusLogin'
# Program Files, not ProgramData: standard users may create folders under
# ProgramData, so one could pre-create the directory that SYSTEM later runs
# code from. Under Program Files only administrators can create it.
$programFiles = if ($env:ProgramW6432) { $env:ProgramW6432 } else { [Environment]::GetFolderPath('ProgramFiles') }
$installDir = Join-Path $programFiles 'CampusLogin'
# Versions before 0.2.0 (the v0.1.0 release) installed here; it is cleaned up after a new install.
$legacyDir = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'CampusLogin'
$installedNames = @('campus-login.exe', 'campus-login.py', 'campus_login_windows.py', 'run-campus-login.ps1',
    'config.json', 'credentials.json', 'campus-login.log', 'campus-login.log.1')
$installedCredential = Join-Path $installDir 'credentials.json'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8

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

function Test-ReparsePoint([string] $Path) {
    $item = Get-Item -LiteralPath $Path -Force
    return [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

function Remove-LegacyInstall {
    # Delete only the files earlier versions wrote, never through a link, and
    # the directory only once it is empty: anyone could have created it.
    if (-not (Test-Path -LiteralPath $legacyDir -PathType Container)) { return }
    if (Test-ReparsePoint $legacyDir) {
        Write-Warning "Not cleaning $legacyDir because it is a link."
        return
    }
    foreach ($name in $installedNames) {
        $path = Join-Path $legacyDir $name
        if ((Test-Path -LiteralPath $path -PathType Leaf) -and -not (Test-ReparsePoint $path)) {
            Remove-Item -LiteralPath $path -Force
        }
    }
    if (@(Get-ChildItem -LiteralPath $legacyDir -Force).Count -eq 0) {
        Remove-Item -LiteralPath $legacyDir -Force
    } else {
        Write-Warning "Left unexpected files in $legacyDir; review and delete them manually."
    }
}

if ($Uninstall) {
    $what = if ($RemoveData) { 'Stop and unregister the campus login task and delete its saved data' } else { 'Stop and unregister the campus login task' }
    if ($PSCmdlet.ShouldProcess($taskName, $what)) {
        Assert-Administrator
        $existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
        if ($existing) {
            Stop-ScheduledTask -TaskName $taskName -TaskPath '\'
            Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false
        }
        if ($RemoveData) {
            if (Test-Path -LiteralPath $installDir) {
                if (Test-ReparsePoint $installDir) {
                    throw "Refusing to delete through a junction or symbolic link: $installDir"
                }
                Remove-Item -LiteralPath $installDir -Recurse -Force
            }
            Remove-LegacyInstall
            Write-Host "Task removed. Saved credentials, logs and installed files were deleted."
        } else {
            Write-Host "Task removed. Installed files and credentials remain in $installDir."
        }
    }
    return
}

# Validate dependencies before changing files or an existing task.
if ($LoginExecutable -and ($LoginScript -or $PythonPath)) {
    throw 'Use -LoginExecutable without -LoginScript or -PythonPath.'
}
if ($LoginExecutable) {
    if (-not (Test-Path -LiteralPath $LoginExecutable -PathType Leaf)) {
        throw "Login executable not found: $LoginExecutable"
    }
    $LoginExecutable = (Resolve-Path -LiteralPath $LoginExecutable).ProviderPath
} else {
    if (-not $LoginScript) {
        $LoginScript = Join-Path $PSScriptRoot 'campus-login.py'
    }
    if (-not (Test-Path -LiteralPath $LoginScript -PathType Leaf)) {
        throw "Login script not found: $LoginScript. Supply a Windows-compatible campus-login.py with -LoginScript."
    }
    $LoginScript = (Resolve-Path -LiteralPath $LoginScript).ProviderPath
    $windowsSource = Join-Path (Split-Path -Parent $LoginScript) 'campus_login_windows.py'
    if (-not (Test-Path -LiteralPath $windowsSource -PathType Leaf)) {
        $windowsSource = Join-Path $PSScriptRoot 'campus_login_windows.py'
    }
    if (-not (Test-Path -LiteralPath $windowsSource -PathType Leaf)) {
        throw 'Windows support module not found. Keep campus_login_windows.py with the installer.'
    }
}
$runnerSource = Join-Path $PSScriptRoot 'run-campus-login.ps1'
if (-not (Test-Path -LiteralPath $runnerSource -PathType Leaf)) {
    throw "Runner not found: $runnerSource. Keep both PowerShell files together."
}
if (-not (Test-Path -LiteralPath $CredentialPath -PathType Leaf)) {
    # Explicit paths never fall back to installed credentials. Check this
    # before probing the restricted installation directory.
    if ($PSBoundParameters.ContainsKey('CredentialPath')) {
        throw "Credential file not found: $CredentialPath"
    }
    $legacyCredential = Join-Path $legacyDir 'credentials.json'
    if (Test-Path -LiteralPath $installedCredential -PathType Leaf) {
        $CredentialPath = $installedCredential
    } elseif (Test-Path -LiteralPath $legacyCredential -PathType Leaf) {
        $CredentialPath = $legacyCredential
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

if (-not $LoginExecutable) {
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
}

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
$config = @{
    network = $Network
    interface = $Interface
}
if ($LoginExecutable) {
    $config.executable = Join-Path $installDir 'campus-login.exe'
} else {
    $config.python = $PythonPath
}
$configJson = $config | ConvertTo-Json

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
foreach ($name in $installedNames) {
    $destination = Join-Path $installDir $name
    if (Test-Path -LiteralPath $destination) {
        Set-PrivatePath $destination
    }
}
$existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $taskName -TaskPath '\'
}
$sources = @($runnerSource)
if ($LoginExecutable) {
    $sources += $LoginExecutable
} else {
    $sources += @($LoginScript, $windowsSource)
}
foreach ($source in $sources) {
    $destination = Join-Path $installDir ([IO.Path]::GetFileName($source))
    # -LoginScript may refer to a differently named file.
    if ($source -eq $LoginScript) { $destination = Join-Path $installDir 'campus-login.py' }
    if ($source -eq $LoginExecutable) { $destination = Join-Path $installDir 'campus-login.exe' }
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
# The task now runs from $installDir; the old copy (with its plain-text
# password) is no longer needed.
Remove-LegacyInstall
Get-ScheduledTask -TaskName $taskName -TaskPath '\' | Select-Object TaskName, State
Write-Host "Logs: $installDir\campus-login.log"
