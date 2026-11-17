<#
.SYNOPSIS
  Set up (first run) and start Copilot on Windows.

.EXAMPLE
  .\run.ps1                                   # set up if needed, then start
  .\run.ps1 -Install                          # also winget-install missing tools
  .\run.ps1 -Engine nemotron                  # pick an ASR engine
  .\run.ps1 -File recordings\x.wav -Assistant scripted   # demo from a recording, no Claude calls
  .\run.ps1 -Dev                              # panel with hot reload (tauri dev)
  .\run.ps1 -Setup                            # set up only
#>
param(
    [string]$Engine,
    [string]$Assistant,
    [string]$File,
    [switch]$Install,
    [switch]$Setup,
    [switch]$Dev
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Step($msg) { Write-Host "> $msg" -ForegroundColor Cyan }

# Native commands don't trip $ErrorActionPreference; stop on their failures too.
function Exec {
    param([Parameter(ValueFromRemainingArguments)] $cmd)
    & $cmd[0] $cmd[1..($cmd.Count - 1)]
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed (exit $LASTEXITCODE): $($cmd -join ' ')" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# ---------------------------------------------------------------- prerequisites
$tools = @(
    @{ cmd = "uv";     id = "astral-sh.uv";       why = "Python + packages for the engine" },
    @{ cmd = "node";   id = "OpenJS.NodeJS.LTS";  why = "builds the panel UI" },
    @{ cmd = "pnpm";   id = "pnpm.pnpm";          why = "panel package manager" },
    @{ cmd = "cargo";  id = "Rustlang.Rustup";    why = "builds the panel window (Tauri). Also needs MSVC C++ build tools." },
    @{ cmd = "claude"; id = "Anthropic.ClaudeCode"; why = "Claude Code CLI; run 'claude' once to log in" }
)
$missing = $tools | Where-Object { -not (Get-Command $_.cmd -ErrorAction SilentlyContinue) }
if ($missing) {
    if ($Install) {
        foreach ($t in $missing) {
            Step "installing $($t.cmd) ($($t.why))"
            winget install --id $t.id -e --accept-source-agreements --accept-package-agreements
        }
        Write-Host "Tools installed. Open a new terminal (to refresh PATH) and run .\run.ps1 again." -ForegroundColor Yellow
        exit 0
    }
    Write-Host "Missing tools:" -ForegroundColor Yellow
    foreach ($t in $missing) { Write-Host ("  {0,-7} winget install {1}   # {2}" -f $t.cmd, $t.id, $t.why) }
    Write-Host "Install them yourself, or run: .\run.ps1 -Install" -ForegroundColor Yellow
    exit 1
}

# ---------------------------------------------------------------- setup (idempotent)
Push-Location "$root\engine"
try {
    Step "engine packages"
    Exec uv sync --extra whisper --quiet
    Step "speech models (first run downloads ~1 GB)"
    Exec uv run copilot models silero parakeet kokoro
} finally { Pop-Location }

Push-Location "$root\panel"
try {
    Step "panel packages"
    Exec pnpm install --frozen-lockfile --reporter=silent
    $exe = "$root\panel\src-tauri\target\release\panel.exe"
    $newest = Get-ChildItem src, src-tauri\src, src-tauri\tauri.conf.json -Recurse -File | Sort-Object LastWriteTime | Select-Object -Last 1
    if (-not $Dev -and (-not (Test-Path $exe) -or (Get-Item $exe).LastWriteTime -lt $newest.LastWriteTime)) {
        Step "building the panel (first build takes a few minutes)"
        Exec pnpm tauri build --no-bundle
    }
} finally { Pop-Location }

if ($Setup) { Write-Host "Setup complete." -ForegroundColor Green; exit 0 }

# ---------------------------------------------------------------- run
$engineArgs = @("run", "copilot", "run")
if ($Engine)    { $engineArgs += @("--engine", $Engine) }
if ($Assistant) { $engineArgs += @("--assistant", $Assistant) }
if ($File)      { $engineArgs += @("--source", "file", "--file", "`"$((Resolve-Path $File).Path)`"") }

$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { "pwsh" } else { "powershell" }
Step "starting engine (its own window; close it to stop listening)"
Start-Process $shell -WorkingDirectory "$root\engine" -ArgumentList "-NoExit", "-Command", "uv $($engineArgs -join ' ')"

Step "starting panel (tray icon, bottom-right)"
if ($Dev) {
    Push-Location "$root\panel"; try { pnpm tauri dev } finally { Pop-Location }
} else {
    Start-Process "$root\panel\src-tauri\target\release\panel.exe"
}
