# Dot-source to import the testable launcher; executing starts all four tunnels.
function Test-Met05Port {
    param([int]$Port)
    $client = New-Object Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return ($task.Wait(200) -and $client.Connected)
    } catch { return $false } finally { $client.Dispose() }
}
function Start-Met05Tunnels {
    param(
        [ValidateRange(1,120)][int]$MaxAttempts = 60,
        [scriptblock]$PortOpen = { param($port) Test-Met05Port $port },
        [scriptblock]$Start = {
            param($spec)
            $remote = "sudo -n k3s kubectl --namespace eventos-development port-forward --address 127.0.0.1 service/$($spec.Service) $($spec.Port):$($spec.RemotePort)"
            $sshArgs = @('-F', 'NUL', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'UpdateHostKeys=no', '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=15',
                '-o', 'IdentitiesOnly=yes', '-i', 'C:/Users/itsis/.ssh/id_ed25519',
                '-L', "127.0.0.1:$($spec.Port):127.0.0.1:$($spec.Port)",
                'azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com', ('"' + $remote + '"'))
            Start-Process -FilePath ssh -ArgumentList $sshArgs -WindowStyle Hidden -PassThru
        },
        [scriptblock]$Probe = {
            param($spec)
            try { return (Invoke-WebRequest -UseBasicParsing -Uri $spec.Url -TimeoutSec 2).StatusCode -eq 200 }
            catch { return $false }
        },
        [scriptblock]$Pause = { Start-Sleep -Milliseconds 500 },
        [scriptblock]$Stop = { param($process) Stop-Process -Id $process.Id -ErrorAction SilentlyContinue }
    )
    $specs = @(
        @{ Port=28000; RemotePort=8000; Service='event-service'; Url='http://127.0.0.1:28000/health/ready' },
        @{ Port=29090; RemotePort=9090; Service='prometheus'; Url='http://127.0.0.1:29090/-/ready' },
        @{ Port=23000; RemotePort=3000; Service='grafana'; Url='http://127.0.0.1:23000/api/health' },
        @{ Port=26686; RemotePort=16686; Service='jaeger-collector'; Url='http://127.0.0.1:26686/api/services' }
    )
    foreach ($spec in $specs) {
        if (& $PortOpen $spec.Port) { throw "Port $($spec.Port) already in use; existing tunnels are not modified" }
    }
    $started = @()
    try {
        # Start every SSH process before waiting for any endpoint.
        foreach ($spec in $specs) {
            $process = & $Start $spec
            if ($null -eq $process) { throw "SSH did not start for $($spec.Port)" }
            $started += [pscustomobject]@{ Spec=$spec; Process=$process }
        }
        for ($attempt=0; $attempt -lt $MaxAttempts; $attempt++) {
            $ready = $true
            foreach ($item in $started) {
                if ($item.Process.HasExited) { throw "SSH exited for $($item.Spec.Port)" }
                if (-not (& $Probe $item.Spec)) { $ready = $false }
            }
            if ($ready) {
                foreach ($item in $started) {
                    if ($item.Process.HasExited) { throw "SSH exited for $($item.Spec.Port)" }
                }
                return $started
            }
            & $Pause
        }
        throw 'Tunnel startup timed out'
    } catch {
        foreach ($item in $started) { & $Stop $item.Process }
        throw
    }
}
if ($MyInvocation.InvocationName -ne '.') { Start-Met05Tunnels }
