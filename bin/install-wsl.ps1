<#
.SYNOPSIS
    Bootstraps a Controlplane development/test environment in WSL 2.

.DESCRIPTION
    Run in Windows PowerShell:

        & ([scriptblock]::Create((Invoke-RestMethod `
            'https://raw.githubusercontent.com/<PUBLIC_REPOSITORY>/main/bin/install-wsl.ps1'))) `
            -Release 'vX.Y.Z'

    This script does exactly one job: fetch the pinned release, verify it
    against its published SHA-256 checksum, extract it, and hand off to
    that release's own provisioning/wsl/install.sh, run inside the target
    WSL distribution. It never configures anything itself beyond what's
    needed to reach that handoff — everything environment-specific lives
    in the release it fetches.

    Elevation: enabling the WSL Windows feature (only needed the first
    time WSL is set up on a machine) requires administrator rights. If
    the current session isn't elevated, this script starts a *separate*
    PowerShell process with Start-Process -Verb RunAs and a temporary,
    process-scoped ExecutionPolicy Bypass. That bypass applies only to
    the child process and ends when it exits — it never changes the
    user or machine execution policy. A Restricted or AllSigned policy
    set by Group Policy cannot be overridden this way; an administrator
    has to change the managed policy or sign the script.

.PARAMETER Release
    Required. The exact tag to install (e.g. v2.5.0, or a pre-release
    tag like v2.6.0-rc.1 for the Test channel). Every install is pinned
    — never point this at a moving target.

.PARAMETER Distro
    The WSL distribution name to provision into. Defaults to
    'Ubuntu-24.04'.

.PARAMETER Force
    Reinstall over an existing installation marker.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^v\d+\.\d+\.\d+(-test\.\d+)?$')]
    [string]$Release,

    [string]$Distro = 'Ubuntu-24.04',

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------

# The public repo releases are published to. This script only ever runs
# by being fetched from that same repo, so it's a plain constant here —
# keep it in sync with the PUBLIC_REPOSITORY repository variable in
# Homelab-Private's Settings, by hand, if it ever changes.
$Repo = 'Fouchger/Homelab'
$Version = $Release.TrimStart('v')
$MarkerFile = Join-Path $env:LOCALAPPDATA 'Controlplane\RELEASE'

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail {
    param([string]$Message)
    Write-Host "error: $Message" -ForegroundColor Red
    exit 1
}

# -----------------------------------------------------------------------
# Idempotency check
# -----------------------------------------------------------------------

if ((Test-Path $MarkerFile) -and (-not $Force)) {
    $installed = Get-Content $MarkerFile -Raw
    Fail "Controlplane $installed is already installed. Re-run with -Force to reinstall over it."
}

# -----------------------------------------------------------------------
# Elevation: only if WSL itself still needs enabling
# -----------------------------------------------------------------------

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

function Test-WslAvailable {
    try {
        $null = wsl.exe --status 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

if (-not (Test-WslAvailable)) {
    if (-not (Test-IsAdministrator)) {
        Write-Step "WSL isn't set up yet — requesting elevation to enable it (this window only, no permanent policy change)"

        $selfInvocation = "& ([scriptblock]::Create((Invoke-RestMethod " +
            "'https://raw.githubusercontent.com/$Repo/main/bin/install-wsl.ps1'))) " +
            "-Release '$Release' -Distro '$Distro'" + $(if ($Force) { ' -Force' } else { '' })

        try {
            Start-Process powershell.exe `
                -Verb RunAs `
                -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $selfInvocation) `
                -Wait
        } catch {
            Fail ("Elevation was declined, or this machine's execution policy is Restricted/AllSigned " +
                  "via Group Policy and can't be bypassed this way. An administrator needs to change " +
                  "the managed policy, or run this script as a signed script.")
        }
        exit $LASTEXITCODE
    }

    Write-Step "Enabling WSL and installing $Distro (this can take a few minutes and may require a reboot)"
    wsl.exe --install -d $Distro
    if ($LASTEXITCODE -ne 0) {
        Fail "wsl.exe --install -d $Distro failed (exit code $LASTEXITCODE)."
    }
}

# -----------------------------------------------------------------------
# Fetch, verify, extract (on the Windows side — the archive is staged
# here, then handed to WSL by path translation)
# -----------------------------------------------------------------------

$WorkDir = Join-Path $env:TEMP "controlplane-install-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $WorkDir | Out-Null
try {
    $Archive = "controlplane-$Version.tar.gz"
    $BaseUrl = "https://github.com/$Repo/releases/download/$Release"
    $ArchivePath = Join-Path $WorkDir $Archive
    $ChecksumPath = "$ArchivePath.sha256"

    Write-Step "Fetching $Release from $Repo"
    try {
        Invoke-WebRequest -Uri "$BaseUrl/$Archive" -OutFile $ArchivePath -UseBasicParsing
    } catch {
        Fail "failed to download $Archive — check the release tag exists at https://github.com/$Repo/releases/tag/$Release"
    }

    try {
        Invoke-WebRequest -Uri "$BaseUrl/$Archive.sha256" -OutFile $ChecksumPath -UseBasicParsing
    } catch {
        Fail "failed to download the checksum file for $Release — refusing to install an unverifiable archive."
    }

    Write-Step "Verifying checksum"
    $expected = (Get-Content $ChecksumPath -Raw).Split(' ')[0].Trim().ToLower()
    $actual = (Get-FileHash -Path $ArchivePath -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) {
        Fail "checksum verification FAILED for $Archive (expected $expected, got $actual). The download is corrupt or has been tampered with — refusing to extract or execute it."
    }

    Write-Step "Extracting"
    tar.exe -xzf $ArchivePath -C $WorkDir
    if ($LASTEXITCODE -ne 0) {
        Fail "tar extraction of $Archive failed (exit code $LASTEXITCODE)."
    }

    $ExtractedDir = Join-Path $WorkDir "controlplane-$Version"
    $NextStageWin = Join-Path $ExtractedDir 'provisioning\wsl\install.sh'
    if (-not (Test-Path $NextStageWin)) {
        Fail "$Release doesn't contain provisioning/wsl/install.sh — this release can't be installed into WSL. If you're seeing this on an official release, please report it."
    }

    # ---------------------------------------------------------------
    # Hand off to the release's own installer, inside WSL
    # ---------------------------------------------------------------

    New-Item -ItemType Directory -Path (Split-Path $MarkerFile) -Force | Out-Null
    Set-Content -Path $MarkerFile -Value $Release -NoNewline

    $extractedWslPath = (wsl.exe -d $Distro -- wslpath -a (Resolve-Path $ExtractedDir).Path.Replace('\', '/')).Trim()

    Write-Step "Handing off to provisioning/wsl/install.sh inside $Distro"
    wsl.exe -d $Distro -- bash -c @"
set -euo pipefail
chmod +x '$extractedWslPath/provisioning/wsl/install.sh'
CONTROLPLANE_RELEASE='$Release' \
CONTROLPLANE_VERSION='$Version' \
CONTROLPLANE_SOURCE_DIR='$extractedWslPath' \
  '$extractedWslPath/provisioning/wsl/install.sh'
"@
    if ($LASTEXITCODE -ne 0) {
        Fail "provisioning/wsl/install.sh exited with code $LASTEXITCODE inside $Distro."
    }
} finally {
    Remove-Item -Path $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
}
