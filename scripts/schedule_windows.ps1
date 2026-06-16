# Registra dos tareas programadas en Windows Task Scheduler:
#   - EventScope-Ingest: corre todos los dias a las 7am
#   - EventScope-Purge:  corre todos los dias a las 8am
#
# Ejecutar como Administrador:
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1

$python = (Get-Command python).Source
$projectDir = Split-Path -Parent $PSScriptRoot

function Register-EventScopeTask {
    param($TaskName, $Argument, $Hour)

    $action = New-ScheduledTaskAction `
        -Execute $python `
        -Argument "-m eventscope.cli $Argument" `
        -WorkingDirectory $projectDir

    $trigger = New-ScheduledTaskTrigger -Daily -At "${Hour}:00"

    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
        -StartWhenAvailable

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -RunLevel Highest `
        -Force | Out-Null

    Write-Host "Tarea registrada: $TaskName (diaria a las ${Hour}hs)"
}

Register-EventScopeTask "EventScope-Ingest" "ingest" 7
Register-EventScopeTask "EventScope-Purge"  "purge"  8

Write-Host ""
Write-Host "Para ver las tareas: Get-ScheduledTask -TaskName 'EventScope*'"
Write-Host "Para correr ahora:   Start-ScheduledTask -TaskName 'EventScope-Ingest'"
Write-Host "Para eliminar:       Unregister-ScheduledTask -TaskName 'EventScope-Ingest' -Confirm:`$false"
