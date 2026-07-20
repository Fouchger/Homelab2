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

    # RouterOS normal exports can still contain explicitly configured script
    # arguments such as binary-backup passwords. Redact quoted values first so
    # RouterOS backslash-newline continuations cannot leave a partial secret.
    $secretName = '(?:password|passphrase|pre-shared-key|private-key|secret|token|community)'
    $patterns = @(
        ('(?ims)(\b' + $secretName + '\s*[=:]\s*)"(?:\\\r?\n\s*|[^"])*"'),
        ('(?im)(\b' + $secretName + '\s*[=:]\s*)[^\s;]+')
    )

    $protected = $Text
    foreach ($pattern in $patterns) {
        $protected = [regex]::Replace($protected, $pattern, '$1<redacted>')
    }
    return $protected
}

function Assert-DiscoveryTextSafe {
    param(
        [AllowEmptyString()][string]$Text,
        [string]$Label
    )

    $secretName = '(?:password|passphrase|pre-shared-key|private-key|secret|token|community)'
    $unsafePattern = '(?im)\b' + $secretName + '\s*[=:]\s*(?!<redacted>)(?:"|[^\s])'
    if ([regex]::IsMatch($Text, $unsafePattern)) {
        throw "Refusing to write $Label because a secret-shaped value remains after redaction."
    }
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

    $protectedText = Protect-DiscoveryText -Text $text
    Assert-DiscoveryTextSafe -Text $protectedText -Label $Destination
    $protectedText | Set-Content -LiteralPath $Destination -Encoding utf8
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
$protectedWindowsOutput = Protect-DiscoveryText -Text ($windowsOutput -join "`n")
$windowsDestination = Join-Path $resolvedOutput "windows-network.txt"
Assert-DiscoveryTextSafe -Text $protectedWindowsOutput -Label $windowsDestination
$protectedWindowsOutput | Set-Content -LiteralPath $windowsDestination -Encoding utf8

Write-Section "Collecting a secret-free MikroTik export"
$routerExportCommand = '/export'
Invoke-DiscoverySsh `
    -Target "$RouterUser@$RouterHost" `
    -RemoteCommand $routerExportCommand `
    -Destination (Join-Path $resolvedOutput "mikrotik-export-redacted.rsc") `
    -IdentityFile $RouterIdentityFile

$routerStateCommand = @(
    ':put ###_SYSTEM_RESOURCE',
    '/system resource print',
    ':put ###_PACKAGES',
    '/system package print',
    ':put ###_INTERFACES',
    '/interface print detail without-paging',
    ':put ###_BRIDGE_PORTS',
    '/interface bridge port print detail without-paging',
    ':put ###_BRIDGE_VLANS',
    '/interface bridge vlan print detail without-paging',
    ':put ###_IP_ADDRESSES',
    '/ip address print detail without-paging',
    ':put ###_ROUTES',
    '/ip route print detail without-paging',
    ':put ###_DHCP_SERVERS',
    '/ip dhcp-server print detail without-paging',
    ':put ###_DHCP_NETWORKS',
    '/ip dhcp-server network print detail without-paging',
    ':put ###_DHCP_LEASES',
    '/ip dhcp-server lease print detail without-paging',
    ':put ###_DNS',
    '/ip dns print',
    ':put ###_FIREWALL_FILTER',
    '/ip firewall filter print stats without-paging',
    ':put ###_FIREWALL_NAT',
    '/ip firewall nat print stats without-paging',
    ':put ###_USERS',
    '/user print detail without-paging',
    ':put ###_USER_GROUPS',
    '/user group print detail without-paging'
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
- Quoted, multiline, and unquoted secret-shaped fields were redacted again locally.
- Collection refuses to write a file if a secret-shaped assignment survives redaction.
- Review every file before sharing it. IP addresses, hostnames, public addresses,
  interface names, and hardware details may remain because they are needed to
  reconstruct the topology.
- Do not commit this directory.
"@
$manifest | Set-Content -LiteralPath (Join-Path $resolvedOutput "README.txt") -Encoding utf8

Write-Section "Discovery complete"
Write-Host "Output: $resolvedOutput" -ForegroundColor Green
Write-Host "Review README.txt and each collected file before sharing them."
