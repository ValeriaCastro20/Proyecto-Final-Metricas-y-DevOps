$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../tunnels.ps1')
function Assert($condition, $message) { if (-not $condition) { throw $message } }
$script:started = @()
$script:stopped = @()
$start = {
    param($spec)
    $script:started += $spec.Port
    [pscustomobject]@{ Id=$spec.Port; HasExited=$false }
}
$stop = { param($process) $script:stopped += $process.Id }
$probe = {
    param($spec)
    Assert ($script:started.Count -eq 4) 'All four tunnels must start before the first probe'
    return $true
}
$ok = @(Start-Met05Tunnels -Start $start -Stop $stop -PortOpen { $false } -Probe $probe -Pause {})
Assert ($ok.Count -eq 4) 'Expected four processes'
Assert ($script:started -contains 28000) 'API tunnel missing'
Assert ($script:stopped.Count -eq 0) 'Successful tunnels must remain running'

$script:started = @()
try {
    Start-Met05Tunnels -Start $start -Stop $stop -PortOpen { param($port) $port -eq 23000 } -Probe $probe -Pause {}
    throw 'Occupied port accepted'
} catch { Assert ($_.Exception.Message -like '*already in use*') 'Unexpected occupied-port result' }
Assert ($script:started.Count -eq 0) 'Must not start or stop existing tunnels'

foreach ($mode in @('timeout', 'exited', 'start-failure')) {
    $script:started = @()
    $script:stopped = @()
    $fake = {
        param($spec)
        if ($mode -eq 'start-failure' -and $spec.Port -eq 23000) { throw 'fixture start failure' }
        $script:started += $spec.Port
        [pscustomobject]@{ Id=$spec.Port; HasExited=($mode -eq 'exited' -and $spec.Port -eq 28000) }
    }
    $failed = $false
    try {
        Start-Met05Tunnels -MaxAttempts 2 -Start $fake -Stop $stop -PortOpen { $false } -Probe { $false } -Pause {}
    } catch { $failed = $true }
    Assert $failed "Must reject $mode"
    Assert ($script:stopped.Count -eq $script:started.Count) 'Clean up only processes started by this invocation'
}
# Exercise the default argument builder without starting SSH.
$script:arguments = @()
function Start-Process {
    param($FilePath, $ArgumentList, $WindowStyle, [switch]$PassThru)
    Assert ($FilePath -eq 'ssh') 'Unexpected process'
    Assert ($WindowStyle -eq 'Hidden') 'SSH windows must be hidden'
    $script:arguments += ,$ArgumentList
    [pscustomobject]@{ Id=$script:arguments.Count; HasExited=$false }
}
$null = Start-Met05Tunnels -PortOpen { $false } -Probe { $true } -Stop $stop -Pause {}
Assert ($script:arguments.Count -eq 4) 'Four independent SSH invocations required'
foreach ($sshCall in $script:arguments) {
    Assert ($sshCall -contains 'StrictHostKeyChecking=yes') 'Strict host verification missing'
    Assert ($sshCall -contains 'ExitOnForwardFailure=yes') 'Forward failure detection missing'
    Assert ($sshCall[-1] -like '*--namespace eventos-development*') 'Wrong namespace'
}
Assert (($script:arguments[0] -join ' ') -like '*28000:8000*') 'API remote port missing'
Write-Output 'PowerShell isolated transport tests passed (no SSH or HTTP executed)'
