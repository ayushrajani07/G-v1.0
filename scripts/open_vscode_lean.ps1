param(
    [string]$WorkspacePath = "$PSScriptRoot\.."
)
# Launch VS Code using the G6 Lean profile for this workspace.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/open_vscode_lean.ps1

function Resolve-CodePath {
    $paths = @(
        "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd",
        "$env:ProgramFiles\Microsoft VS Code\bin\code.cmd",
        "code"  # rely on PATH
    )
    foreach ($p in $paths) {
        try {
            $cmd = (Get-Command $p -ErrorAction SilentlyContinue)
            if ($cmd) { return $cmd.Source }
        } catch {}
    }
    return $null
}

$code = Resolve-CodePath
if (-not $code) {
    Write-Error "Could not locate VS Code executable (code). Ensure VS Code is installed and code is on PATH."
    exit 1
}

# Ensure profile name exists; if not yet imported, VS Code will prompt
$profileName = 'G6 Lean'

# Launch Code with profile targeting the workspace path
& $code --profile $profileName $WorkspacePath
