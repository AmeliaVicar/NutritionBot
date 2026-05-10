[CmdletBinding()]
param(
    [string]$RepoDir = "",
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [string]$PythonExe = "",
    [switch]$RestartBot,
    [switch]$SkipInstallRequirements
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoDir)) {
    $RepoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $RepoDir = (Resolve-Path $RepoDir).Path
}

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $venvPython = Join-Path $RepoDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        $PythonExe = $venvPython
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -ne $pythonCommand) {
            $PythonExe = $pythonCommand.Source
        } else {
            $pyCommand = Get-Command py -ErrorAction SilentlyContinue
            if ($null -ne $pyCommand) {
                $PythonExe = $pyCommand.Source
            } else {
                $PythonExe = "python"
            }
        }
    }
}

$LogDir = Join-Path $RepoDir "logs"
$LogFile = Join-Path $LogDir "auto-update.log"
$PidFile = Join-Path $LogDir "nutritionbot.pid"
$InstallMarkerFile = Join-Path $LogDir "last-installed-commit.txt"
$LockFile = Join-Path $LogDir "auto-update.lock"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Write-DeployLog {
    param([string]$Message)

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogFile -Value "[$stamp] $Message" -Encoding UTF8
}

function Invoke-Logged {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-DeployLog ("RUN: " + $FilePath + " " + ($Arguments -join " "))
    $output = & $FilePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE

    foreach ($line in $output) {
        Write-DeployLog ("  " + $line)
    }

    if ($exitCode -ne 0) {
        throw "$FilePath exited with code $exitCode"
    }

    return $output
}

function Invoke-Git {
    param([string[]]$Arguments)

    $gitArgs = @("-C", $RepoDir) + $Arguments
    return Invoke-Logged -FilePath "git" -Arguments $gitArgs
}

function Get-LastOutputLine {
    param($Output)

    if ($null -eq $Output) {
        return ""
    }

    $line = $Output | Select-Object -Last 1
    if ($null -eq $line) {
        return ""
    }

    return $line.ToString().Trim()
}

function Get-ManagedBotProcess {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $null
    }

    $pidText = (Get-Content -LiteralPath $PidFile -Raw -ErrorAction SilentlyContinue).Trim()
    if (-not ($pidText -match "^\d+$")) {
        return $null
    }

    try {
        return Get-Process -Id ([int]$pidText) -ErrorAction Stop
    } catch {
        Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
        return $null
    }
}

function Start-ManagedBot {
    $existing = Get-ManagedBotProcess
    if ($null -ne $existing) {
        Write-DeployLog "Bot is already running with pid $($existing.Id)."
        return
    }

    $botScript = Join-Path $RepoDir "src\NutritionBot.py"
    if (-not (Test-Path -LiteralPath $botScript)) {
        throw "Bot script not found: $botScript"
    }

    $stdout = Join-Path $LogDir "bot.out.log"
    $stderr = Join-Path $LogDir "bot.err.log"

    $process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-u", $botScript) `
        -WorkingDirectory $RepoDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru

    Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ASCII
    Write-DeployLog "Started bot with pid $($process.Id)."
}

function Stop-ManagedBot {
    $existing = Get-ManagedBotProcess
    if ($null -eq $existing) {
        Write-DeployLog "No managed bot process to stop."
        return
    }

    Write-DeployLog "Stopping bot pid $($existing.Id)."
    Stop-Process -Id $existing.Id -Force
    Start-Sleep -Seconds 2
    Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
}

function Restart-ManagedBot {
    Stop-ManagedBot
    Start-ManagedBot
}

$lockStream = $null
try {
    try {
        $lockStream = [System.IO.File]::Open(
            $LockFile,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    } catch {
        Write-DeployLog "Another auto-update run is active; skipping."
        return
    }

    Write-DeployLog "Auto-update started for $RepoDir."

    if (-not (Test-Path -LiteralPath (Join-Path $RepoDir ".git"))) {
        throw "RepoDir is not a git repository: $RepoDir"
    }

    $currentBranch = Get-LastOutputLine (Invoke-Git @("branch", "--show-current"))
    if ($currentBranch -ne $Branch) {
        Write-DeployLog "Current branch is '$currentBranch', expected '$Branch'; skipping git update."
        if ($RestartBot) {
            Start-ManagedBot
        }
        return
    }

    $statusOutput = Invoke-Git @("status", "--porcelain", "--untracked-files=no")
    if ($statusOutput) {
        Write-DeployLog "Working tree has local changes; skipping git update."
        if ($RestartBot) {
            Start-ManagedBot
        }
        return
    }

    Invoke-Git @("fetch", $Remote, $Branch) | Out-Null

    $localHead = Get-LastOutputLine (Invoke-Git @("rev-parse", "HEAD"))
    $remoteHead = Get-LastOutputLine (Invoke-Git @("rev-parse", "$Remote/$Branch"))
    $updated = $false

    if ($localHead -ne $remoteHead) {
        Write-DeployLog "Updating $Branch from $localHead to $remoteHead."
        Invoke-Git @("pull", "--ff-only", $Remote, $Branch) | Out-Null
        $updated = $true
    } else {
        Write-DeployLog "Already up to date at $localHead."
    }

    $currentHead = Get-LastOutputLine (Invoke-Git @("rev-parse", "HEAD"))
    $lastInstalled = ""
    if (Test-Path -LiteralPath $InstallMarkerFile) {
        $lastInstalled = (Get-Content -LiteralPath $InstallMarkerFile -Raw -ErrorAction SilentlyContinue).Trim()
    }

    if (-not $SkipInstallRequirements -and $currentHead -ne $lastInstalled) {
        $requirements = Join-Path $RepoDir "requirements.txt"
        if (Test-Path -LiteralPath $requirements) {
            Invoke-Logged -FilePath $PythonExe -Arguments @("-m", "pip", "install", "-r", $requirements) | Out-Null
        }
        Set-Content -LiteralPath $InstallMarkerFile -Value $currentHead -Encoding ASCII
    }

    if ($RestartBot) {
        if ($updated) {
            Restart-ManagedBot
        } else {
            Start-ManagedBot
        }
    }

    Write-DeployLog "Auto-update finished."
} catch {
    Write-DeployLog ("ERROR: " + $_.Exception.Message)
    throw
} finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
    Remove-Item -LiteralPath $LockFile -ErrorAction SilentlyContinue
}
