param(
    [Parameter(Mandatory=$true)][string]$ScriptFile,
    [Parameter(Mandatory=$true)][string]$LogName,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
if ([IO.Path]::GetFileName($LogName) -ne $LogName) { throw 'LogName must be a filename' }
if (Test-Path -LiteralPath $OutputDirectory) { throw 'OutputDirectory must be new; historical evidence is read-only' }
$null = New-Item -ItemType Directory -Path $OutputDirectory
$body = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $ScriptFile)) -replace "`r", ""
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($body + "`n"))
$ErrorActionPreference = 'Continue'
$result = $encoded | & ssh -F NUL -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o ConnectTimeout=15 -o IdentitiesOnly=yes -i C:/Users/itsis/.ssh/id_ed25519 azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com 'bash -o pipefail -c "base64 --ignore-garbage -d | bash"' 2>&1
$exitCode = $LASTEXITCODE
@("UTC=$([DateTime]::UtcNow.ToString('o'))", "SCRIPT=$ScriptFile", $result, "EXIT_CODE=$exitCode") |
    Out-File -LiteralPath (Join-Path $OutputDirectory $LogName) -Encoding utf8
$result | Write-Output
exit $exitCode
