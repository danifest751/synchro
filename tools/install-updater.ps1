param([Parameter(Mandatory = $true)][string]$ExtensionDir)
$ErrorActionPreference = 'Stop'
$targetDir = (Resolve-Path -LiteralPath $ExtensionDir).Path
$manifest = Get-Content -LiteralPath (Join-Path $targetDir 'manifest.json') -Raw | ConvertFrom-Json
if (-not $manifest.name.StartsWith('Synchro')) { throw 'Select an installed Synchro extension folder' }
$updaterScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'update_extension.py')).Path
$pythonPath = (Get-Command python).Source
$hiddenPython = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $hiddenPython)) { throw 'Python for Windows with pythonw.exe is required' }
$action = New-ScheduledTaskAction -Execute $hiddenPython -Argument ('"' + $updaterScript + '" --target "' + $targetDir + '"')
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName 'Synchro GitHub extension updates' -Action $action -Trigger $trigger -Settings $settings -Description 'Update the unpacked Synchro extension from verified GitHub Releases, preserving its server settings.' -Force | Out-Null
Write-Output 'Synchro GitHub updater installed: checks every 15 minutes while this user is signed in.'
