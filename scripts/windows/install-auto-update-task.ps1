[CmdletBinding()]
param(
    [string]$RepoDir = "",
    [string]$TaskName = "NutritionBot Auto Update",
    [int]$IntervalMinutes = 1,
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [string]$PythonExe = ""
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

$autoUpdateScript = Join-Path $RepoDir "scripts\windows\auto-update.ps1"
if (-not (Test-Path -LiteralPath $autoUpdateScript)) {
    throw "Auto-update script not found: $autoUpdateScript"
}

$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$actionArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$autoUpdateScript`"",
    "-RepoDir", "`"$RepoDir`"",
    "-Remote", "`"$Remote`"",
    "-Branch", "`"$Branch`"",
    "-PythonExe", "`"$PythonExe`"",
    "-RestartBot"
) -join " "

$action = New-ScheduledTaskAction -Execute $powershellExe -Argument $actionArgs -WorkingDirectory $RepoDir
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Pull latest NutritionBot code from git and keep the bot process running." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "RepoDir: $RepoDir"
Write-Host "PythonExe: $PythonExe"
Write-Host "IntervalMinutes: $IntervalMinutes"
Write-Host "Logs: $(Join-Path $RepoDir 'logs\auto-update.log')"
