param(
    [Parameter(Mandatory=$true)][string]$Server,
    [Parameter(Mandatory=$true)][string]$IdentityFile
)
$ErrorActionPreference = 'Stop'
$synchroRoot = Split-Path -Parent $PSScriptRoot
$proxyPath = Join-Path $synchroRoot 'deploy/youtube_proxy.py'
$proxyProcess = $null
try {
    if (-not (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 18769 -State Listen -ErrorAction SilentlyContinue)) {
        $proxyProcess = Start-Process -FilePath 'python' -ArgumentList @('"' + $proxyPath + '"') -PassThru -WindowStyle Hidden
        Start-Sleep -Seconds 1
        if ($proxyProcess.HasExited) { throw 'Could not start the local YouTube proxy' }
    }
    $sshArguments = @('-N', '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3', '-i', $IdentityFile, '-R', '127.0.0.1:18770:127.0.0.1:18769')
    if (-not (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8768 -State Listen -ErrorAction SilentlyContinue)) {
        $sshArguments += @('-L', '127.0.0.1:8768:127.0.0.1:8768')
    }
    $sshArguments += $Server
    & ssh @sshArguments
} finally {
    if ($proxyProcess -and -not $proxyProcess.HasExited) { Stop-Process -Id $proxyProcess.Id }
}
