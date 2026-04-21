<#
Run this on the remote Windows computer. It does not install anything and does
not require administrator rights. It prints the values and commands needed from
the local/control computer.
#>

param(
    [string]$WafflePath = "",
    [string]$CondaPath = "",
    [string]$EnvName = "Waffle"
)

function Write-Section($Text) {
    Write-Host ""
    Write-Host "=== $Text ==="
}

function Quote-Arg($Value) {
    return '"' + ($Value -replace '"', '\"') + '"'
}

Write-Section "SSH server status"
$sshd = Get-Service sshd -ErrorAction SilentlyContinue
if ($null -eq $sshd) {
    Write-Host "OpenSSH Server service was not found. Paramiko/SSH cannot connect until an administrator enables OpenSSH Server."
} else {
    Write-Host ("Status: {0}" -f $sshd.Status)
    Write-Host ("DisplayName: {0}" -f $sshd.DisplayName)
    if ($sshd.Status -ne "Running") {
        Write-Host "The service exists but is not running. It must be started before remote SSH works."
    }
}

Write-Section "Remote identity"
$remoteUser = $env:USERNAME
$whoami = whoami
$hostName = hostname
Write-Host ("whoami: {0}" -f $whoami)
Write-Host ("hostname: {0}" -f $hostName)
Write-Host ("SSH username to try: {0}" -f $remoteUser)

Write-Section "Candidate IPv4 addresses"
$ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -ExpandProperty IPAddress)
if (-not $ips) {
    $ips = @("REMOTE_HOST_OR_IP")
    Write-Host "No non-loopback IPv4 address was detected with Get-NetIPAddress. Run ipconfig manually and use the active adapter IPv4 address."
} else {
    foreach ($ip in $ips) { Write-Host $ip }
}
$firstIp = $ips[0]

Write-Section "Conda path"
if (-not $CondaPath) {
    $condaCmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($condaCmd) {
        $CondaPath = $condaCmd.Source
    } else {
        $knownConda = @(
            "$env:USERPROFILE\miniconda3\condabin\conda.bat",
            "$env:LOCALAPPDATA\miniconda3\condabin\conda.bat",
            "$env:USERPROFILE\miniforge3\condabin\conda.bat",
            "$env:LOCALAPPDATA\miniforge3\condabin\conda.bat",
            "$env:LOCALAPPDATA\anaconda3\condabin\conda.bat",
            "$env:USERPROFILE\anaconda3\condabin\conda.bat"
        )
        foreach ($candidate in $knownConda) {
            if (Test-Path $candidate) {
                $CondaPath = $candidate
                break
            }
        }
    }
}
if ($CondaPath) {
    Write-Host $CondaPath
} else {
    $CondaPath = "REMOTE_CONDA_PATH"
    Write-Host "Conda was not found automatically. Run 'where conda' manually and use the full path to conda.bat."
}

Write-Section "WAFFLE v2 path"
if (-not $WafflePath) {
    if (Test-Path ".\near_realtime_aia_pipeline.py") {
        $WafflePath = (Get-Location).Path
    } else {
        $WafflePath = "REMOTE_WAFFLE_V2_PATH"
    }
}
Write-Host $WafflePath
if ($WafflePath -ne "REMOTE_WAFFLE_V2_PATH") {
    $pipeline = Join-Path $WafflePath "near_realtime_aia_pipeline.py"
    $envFile = Join-Path $WafflePath "waffle_env.yml"
    Write-Host ("near_realtime_aia_pipeline.py exists: {0}" -f (Test-Path $pipeline))
    Write-Host ("waffle_env.yml exists: {0}" -f (Test-Path $envFile))
}

Write-Section "Run these from the local/control computer"
Write-Host "First test plain SSH:"
Write-Host ("ssh {0}@{1} `"hostname`"" -f $remoteUser, $firstIp)

Write-Host ""
Write-Host "Then test that WAFFLE can start through SSH attached to your terminal:"
$remoteCmd = "cd /d `"$WafflePath`" && `"$CondaPath`" run --no-capture-output -n $EnvName python near_realtime_aia_pipeline.py"
Write-Host ("ssh {0}@{1} {2}" -f $remoteUser, $firstIp, (Quote-Arg $remoteCmd))

Write-Host ""
Write-Host "Then start it with the Python Paramiko helper from this repo:"
Write-Host ("python Waffle/remote_start_waffle.py --host {0} --user {1} --password --remote-root {2} --conda {3}" -f $firstIp, $remoteUser, (Quote-Arg $WafflePath), (Quote-Arg $CondaPath))

Write-Host ""
Write-Host "If you need to update the remote Waffle env first, add: --update-env"
Write-Host "If you want it detached after testing attached mode, add: --background"
