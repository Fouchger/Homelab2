[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RouterHost,

    [string]$RouterUser = "admin",

    [string]$RouterIdentityFile = "",

    [Parameter(Mandatory = $true)]
    [string]$ProxmoxHost,

    [string]$ProxmoxUser = "root",

    [string]$ProxmoxIdentityFile = "",

    [string]$OutputDirectory = "",

    [switch]$AllowInteractiveAuthentication
)

$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Protect-DiscoveryText {
    param([AllowEmptyString()][string]$Text)

    # RouterOS exports hide sensitive values by default. These replacements are a
    # second line of defence for output from other read-only commands.
    $patterns = @(
        '(?im)(password\s*[=:]\s*)\S+',
        '(?im)(passphrase\s*[=:]\s*)\S+',
        '(?im)(pre-shared-key\s*[=:]\s*)\S+',
        '(?im)(private-key\s*[=:]\s*)\S+',
        '(?im)(secret\s*[=:]\s*)\S+',
        '(?im)(token\s*[=:]\s*)\S+',
        '(?im)(community\s*[=:]\s*)\S+'
    )

    $protected = $Text
    foreach ($pattern in $patterns) {
        $protected = [regex]::Replace($protected, $pattern, '$1<redacted>')
    }
    return $protected
}

function Invoke-DiscoverySsh {
    param(
        [string]$Target,
        [string]$RemoteCommand,
        [string]$Destination,
        [string]$IdentityFile = "",
        [switch]$EncodeBashScript
    )

    Write-Host "Collecting $Destination from $Target"
    $batchMode = if ($AllowInteractiveAuthentication) { "no" } else { "yes" }
    $sshArguments = @(
        "-o", "BatchMode=$batchMode",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new"
    )
    if (-not [string]::IsNullOrWhiteSpace($IdentityFile)) {
        $sshArguments += @("-i", $IdentityFile)
    }
    if ($EncodeBashScript) {
        $normalizedCommand = $RemoteCommand.Replace("`r`n", "`n").Replace("`r", "`n")
        $commandBytes = [System.Text.Encoding]::UTF8.GetBytes($normalizedCommand)
        $encodedCommand = [Convert]::ToBase64String($commandBytes)
        $RemoteCommand = "printf '%s' '$encodedCommand' | base64 -d | bash"
    }

    $output = & ssh @sshArguments $Target $RemoteCommand 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String)

    if ($exitCode -ne 0) {
        $text = "Collection failed with SSH exit code $exitCode.`n$text"
        Write-Warning "Collection from $Target failed. See $Destination."
    }

    Protect-DiscoveryText -Text $text |
        Set-Content -LiteralPath $Destination -Encoding utf8
}

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "Windows OpenSSH client was not found. Enable the OpenSSH Client optional feature first."
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputDirectory = Join-Path (Get-Location) "discovery-output\$timestamp"
}

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null

Write-Section "Collecting Windows laptop network state"
$windowsOutput = @()
$windowsOutput += "Collected: $(Get-Date -Format o)"
$windowsOutput += "Computer: $env:COMPUTERNAME"
$windowsOutput += ""
$windowsOutput += "### Windows"
$windowsOutput += (Get-ComputerInfo |
    Select-Object WindowsProductName, WindowsVersion, OsBuildNumber |
    Format-List | Out-String)
$windowsOutput += "### Active adapters"
$windowsOutput += (Get-NetAdapter |
    Where-Object Status -eq "Up" |
    Select-Object Name, InterfaceDescription, Status, LinkSpeed |
    Format-Table -AutoSize | Out-String)
$windowsOutput += "### IP configuration"
$windowsOutput += (Get-NetIPConfiguration -Detailed | Format-List | Out-String)
$windowsOutput += "### IPv4 routes"
$windowsOutput += (Get-NetRoute -AddressFamily IPv4 |
    Select-Object DestinationPrefix, NextHop, InterfaceAlias, RouteMetric |
    Sort-Object DestinationPrefix, RouteMetric |
    Format-Table -AutoSize | Out-String)
Protect-DiscoveryText -Text ($windowsOutput -join "`n") |
    Set-Content -LiteralPath (Join-Path $resolvedOutput "windows-network.txt") -Encoding utf8

Write-Section "Collecting a secret-free MikroTik export"
$routerExportCommand = '/export'
Invoke-DiscoverySsh `
    -Target "$RouterUser@$RouterHost" `
    -RemoteCommand $routerExportCommand `
    -Destination (Join-Path $resolvedOutput "mikrotik-export-redacted.rsc") `
    -IdentityFile $RouterIdentityFile

$routerStateCommand = @(
    '/system resource print',
    '/system package print',
    '/interface print detail without-paging',
    '/interface bridge port print detail without-paging',
    '/interface bridge vlan print detail without-paging',
    '/ip address print detail without-paging',
    '/ip route print detail without-paging',
    '/ip dhcp-server print detail without-paging',
    '/ip dhcp-server network print detail without-paging',
    '/ip dns print',
    '/ip firewall filter print stats without-paging',
    '/ip firewall nat print stats without-paging'
) -join '; '
Invoke-DiscoverySsh `
    -Target "$RouterUser@$RouterHost" `
    -RemoteCommand $routerStateCommand `
    -Destination (Join-Path $resolvedOutput "mikrotik-runtime-redacted.txt") `
    -IdentityFile $RouterIdentityFile

Write-Section "Collecting read-only Proxmox state"
$proxmoxCommand = @'
set -u
section() { printf '\n### %s\n' "$1"; }
section "Version"
pveversion -v
section "Host"
hostnamectl
section "Addresses"
ip -brief address
section "Links and bridges"
ip -details link show
section "Bridge VLANs"
bridge vlan show
section "Network configuration"
cat /etc/network/interfaces
for file in /etc/network/interfaces.d/*; do
  [ -f "$file" ] || continue
  printf '\n## %s\n' "$file"
  cat "$file"
done
section "Storage"
pvesm status
cat /etc/pve/storage.cfg
section "Filesystems"
findmnt
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS
section "Guests"
pvesh get /cluster/resources --type vm --output-format json
pct list
qm list
section "Guest configuration (sensitive fields removed)"
for file in /etc/pve/lxc/*.conf /etc/pve/qemu-server/*.conf; do
  [ -f "$file" ] || continue
  printf '\n## %s\n' "$file"
  sed -E '/(password|sshkeys|token|secret|keyfile)/Id' "$file"
done
section "Failed services"
systemctl --failed --no-pager
'@
Invoke-DiscoverySsh `
    -Target "$ProxmoxUser@$ProxmoxHost" `
    -RemoteCommand $proxmoxCommand `
    -Destination (Join-Path $resolvedOutput "proxmox-redacted.txt") `
    -IdentityFile $ProxmoxIdentityFile `
    -EncodeBashScript

$manifest = @"
Homelab discovery bundle
Collected: $(Get-Date -Format o)

Files:
- windows-network.txt
- mikrotik-export-redacted.rsc
- mikrotik-runtime-redacted.txt
- proxmox-redacted.txt

Safety:
- Collection commands are read-only.
- RouterOS normal export redaction was used; show-sensitive was not requested.
- Common secret-shaped fields were redacted again locally.
- Review every file before sharing it. IP addresses, hostnames, public addresses,
  interface names, and hardware details may remain because they are needed to
  reconstruct the topology.
- Do not commit this directory.
"@
$manifest | Set-Content -LiteralPath (Join-Path $resolvedOutput "README.txt") -Encoding utf8

Write-Section "Discovery complete"
Write-Host "Output: $resolvedOutput" -ForegroundColor Green
Write-Host "Review README.txt and each collected file before sharing them."
