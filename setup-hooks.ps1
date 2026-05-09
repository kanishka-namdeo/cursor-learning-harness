<#
.SYNOPSIS
    Install Cursor Learning Harness hooks into an existing workspace.

.DESCRIPTION
    Copies the .cursor/ directory structure (hooks, rules, config) into a target
    workspace so teams can adopt the learning harness mid-project.

    Excludes runtime state (sessions, logs, SQLite) and user secrets (llm.env).
    Does NOT create venv or install dependencies -- those are managed by the
    target project's own workflow.

.PARAMETER TargetDir
    The target workspace directory. Defaults to the current directory.

.EXAMPLE
    .\setup-hooks.ps1
    Install hooks into the current directory.

.EXAMPLE
    .\setup-hooks.ps1 -TargetDir "D:\my-project"
    Install hooks into a specific directory.

.EXAMPLE
    .\setup-hooks.ps1 -WhatIf
    Preview what would be copied without making any changes.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Position = 0)]
    [string]$TargetDir = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

# --- Helper functions ---

function Write-Status {
    param([string]$Message)
    Write-Host "[SETUP] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# --- Resolve target directory ---
$TargetDir = Resolve-Path -Path $TargetDir -ErrorAction SilentlyContinue
if (-not $TargetDir -or -not (Test-Path $TargetDir)) {
    Write-Err "Target directory does not exist: $TargetDir"
    exit 1
}
Write-Status "Target directory: $TargetDir"

# --- Check Python version ---
Write-Status "Checking Python..."
try {
    $PythonVersion = & python --version 2>&1
    if ($PythonVersion -match "Python (\d+)\.(\d+)") {
        $Major = [int]$Matches[1]
        $Minor = [int]$Matches[2]
        if ($Major -lt 3 -or ($Major -eq 3 -and $Minor -lt 13)) {
            Write-Err "Python 3.13+ is required (found $Major.$Minor)"
            Write-Err "Download from https://www.python.org/downloads/"
            exit 1
        }
        Write-Success "Python $Major.$Minor detected"
    } else {
        Write-Err "Could not parse Python version: $PythonVersion"
        exit 1
    }
} catch {
    Write-Err "Python is not installed or not in PATH"
    Write-Err "Download from https://www.python.org/downloads/"
    exit 1
}

# --- Source directory (where this script lives) ---
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$SourceCursorDir = Join-Path $ScriptDir ".cursor"
if (-not (Test-Path $SourceCursorDir)) {
    Write-Err "Cannot find .cursor/ directory in the script location: $ScriptDir"
    Write-Err "Run this script from the root of the cursor-learning-harness repository."
    exit 1
}

# --- Check for existing .cursor/ in target ---
$TargetCursorDir = Join-Path $TargetDir ".cursor"
if (Test-Path $TargetCursorDir) {
    Write-Warn "A .cursor/ directory already exists in the target workspace."
    $Choice = Read-Host "Merge (skip existing files) or Abort? Type 'merge' or 'abort'"
    if ($Choice -ne "merge") {
        Write-Status "Aborted by user."
        exit 0
    }
    Write-Status "Merge mode: existing files will be preserved."
}

# --- Define what to copy and exclude ---
# Items to copy from .cursor/ root: hooks.json, llm.env.example
# Items to copy as directories: hooks/ (minus state/, plans/), rules/
# Do NOT copy: llm.env (secrets), hooks/state/ (runtime), plans/ (internal)

$ItemsToCopy = @(
    "hooks.json",
    "llm.env.example",
    "hooks",
    "rules"
)

function Copy-CursorItem {
    param(
        [string]$ItemName,
        [string]$Source,
        [string]$Dest,
        [bool]$SkipExisting = $false
    )

    $SourcePath = Join-Path $Source $ItemName
    $DestPath = Join-Path $Dest $ItemName

    if (-not (Test-Path $SourcePath)) {
        Write-Warn "Source not found, skipping: $ItemName"
        return
    }

    # Skip llm.env if user has their own
    if ($ItemName -eq "llm.env" -and (Test-Path $DestPath)) {
        Write-Status "Preserving existing llm.env"
        return
    }

    if ($SkipExisting -and (Test-Path $DestPath)) {
        Write-Status "Already exists, skipping: $ItemName"
        return
    }

    if ($PSCmdlet.ShouldProcess($DestPath, "Copy $ItemName")) {
        if (Test-Path $SourcePath -PathType Container) {
            # It's a directory -- copy recursively with exclusions
            # Create the destination directory
            if (-not (Test-Path $DestPath)) {
                New-Item -ItemType Directory -Path $DestPath -Force | Out-Null
            }

            # Copy all items except excluded ones
            Get-ChildItem -Path $SourcePath -Recurse | ForEach-Object {
                $RelativePath = $_.FullName.Substring($SourcePath.Length + 1)
                # Skip if any path component is in the exclusion list
                $PathComponents = $RelativePath -split '[\\/]'
                $ShouldSkip = $false
                foreach ($Component in $PathComponents) {
                    if ($Component -eq "state" -or $Component -eq "plans") {
                        $ShouldSkip = $true
                        break
                    }
                }
                if ($ShouldSkip) {
                    return
                }

                $TargetPath = Join-Path $DestPath $RelativePath
                if ($_.PSIsContainer) {
                    if (-not (Test-Path $TargetPath)) {
                        if ($PSCmdlet.ShouldProcess($TargetPath, "Create directory")) {
                            New-Item -ItemType Directory -Path $TargetPath -Force | Out-Null
                        }
                    }
                } else {
                    # Only copy if merge mode allows it
                    if ($SkipExisting -and (Test-Path $TargetPath)) {
                        Write-Status "  Skipping existing: $RelativePath"
                        return
                    }
                    $TargetParent = Split-Path $TargetPath -Parent
                    if (-not (Test-Path $TargetParent)) {
                        New-Item -ItemType Directory -Path $TargetParent -Force | Out-Null
                    }
                    if ($PSCmdlet.ShouldProcess($TargetPath, "Copy file")) {
                        Copy-Item -Path $_.FullName -Destination $TargetPath -Force
                        Write-Status "  Copied: $RelativePath"
                    }
                }
            }
        } else {
            # It's a file
            if (-not (Test-Path (Split-Path $DestPath -Parent))) {
                New-Item -ItemType Directory -Path (Split-Path $DestPath -Parent) -Force | Out-Null
            }
            Copy-Item -Path $SourcePath -Destination $DestPath -Force
            Write-Status "  Copied: $ItemName"
        }
    }
}

# --- Execute copy ---
Write-Status "Copying Cursor Learning Harness hooks..."
foreach ($Item in $ItemsToCopy) {
    $MergeMode = (Test-Path $TargetCursorDir) -and ($Choice -eq "merge")
    Copy-CursorItem -ItemName $Item -Source $SourceCursorDir -Dest $TargetCursorDir -SkipExisting $MergeMode
}

# --- Copy project files ---
$ProjectFiles = @("pyproject.toml", "install.bat", "install.sh")
foreach ($File in $ProjectFiles) {
    $SourceFile = Join-Path $ScriptDir $File
    $DestFile = Join-Path $TargetDir $File
    if (Test-Path $SourceFile) {
        if ($PSCmdlet.ShouldProcess($DestFile, "Copy $File")) {
            Copy-Item -Path $SourceFile -Destination $DestFile -Force
            Write-Status "  Copied: $File"
        }
    }
}

# --- Ensure state directory and .gitkeep exist ---
$StateDir = Join-Path $TargetCursorDir "hooks/state"
if ($PSCmdlet.ShouldProcess($StateDir, "Create state directory")) {
    if (-not (Test-Path $StateDir)) {
        New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    }
    $GitKeep = Join-Path $StateDir ".gitkeep"
    if (-not (Test-Path $GitKeep)) {
        Set-Content -Path $GitKeep -Value "" -Force
    }
}

# --- Copy llm.env.example -> llm.env only if llm.env absent ---
$LlmEnv = Join-Path $TargetCursorDir "llm.env"
$LlmEnvExample = Join-Path $TargetCursorDir "llm.env.example"
if (-not (Test-Path $LlmEnv) -and (Test-Path $LlmEnvExample)) {
    if ($PSCmdlet.ShouldProcess($LlmEnv, "Create llm.env from example")) {
        Copy-Item -Path $LlmEnvExample -Destination $LlmEnv
        Write-Status "  Created llm.env from example"
    }
}

# --- Summary ---
Write-Host ""
Write-Success "Cursor Learning Harness hooks installed successfully!"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Edit .cursor\llm.env with your LLM API key"
Write-Host "  2. Install dependencies:"
Write-Host "     pip install -e `".[dashboard,ml]`""
Write-Host "  3. Open the project in Cursor -- hooks auto-activate on session start"
Write-Host ""
Write-Host "To launch the dashboard:"
Write-Host "  streamlit run .cursor\hooks\dashboard\dashboard.py"
Write-Host ""
