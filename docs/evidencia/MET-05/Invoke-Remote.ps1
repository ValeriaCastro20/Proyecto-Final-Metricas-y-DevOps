param([Parameter(Mandatory=$true)][string]$ScriptFile,[Parameter(Mandatory=$true)][string]$LogName)
$ErrorActionPreference = 'Continue'
$body = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $ScriptFile)) -replace "`r", ""
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($body + "`n"))
$result = $encoded | & ssh -F NUL -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o ConnectTimeout=15 -o IdentitiesOnly=yes -i C:/Users/itsis/.ssh/id_ed25519 azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com 'base64 --ignore-garbage -d | bash' 2>&1
$exitCode = $LASTEXITCODE
@("UTC=$([DateTime]::UtcNow.ToString('o'))", "SCRIPT=$ScriptFile", $result, "EXIT_CODE=$exitCode") | Out-File -LiteralPath (Join-Path $PSScriptRoot $LogName) -Encoding utf8
$result | Write-Output
exit $exitCode
