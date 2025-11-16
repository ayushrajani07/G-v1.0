# Git Operations Script - Simple ASCII version
# Run with: .\git_ops.ps1

function Show-Menu {
    Clear-Host
    Write-Host "================================"
    Write-Host "   Git Operations Menu"
    Write-Host "================================"
    Write-Host ""
    Write-Host "1. Status"
    Write-Host "2. Add all + Commit + Push (Full Sync)"
    Write-Host "3. Commit + Push (Quick)"
    Write-Host "4. Push only"
    Write-Host "5. Pull"
    Write-Host "6. Force push (safe - with lease)"
    Write-Host "7. Amend last commit"
    Write-Host "8. Show recent commits"
    Write-Host "9. Unstage all"
    Write-Host "0. Exit"
    Write-Host ""
}

$branch = git rev-parse --abbrev-ref HEAD 2>$null
if (-not $branch) { $branch = "main" }
$remote = git remote 2>$null | Select-Object -First 1
if (-not $remote) { $remote = "origin" }

while ($true) {
    Show-Menu
    Write-Host "Current: $branch @ $remote"
    Write-Host ""
    $choice = Read-Host "Choice"
    
    switch ($choice) {
        "1" {
            git status
            Read-Host "Press Enter"
        }
        "2" {
            Write-Host "Full Sync: Add + Commit + Push"
            git status --short
            $msg = Read-Host "Commit message"
            if ($msg) {
                git add -A
                git commit -m $msg
                git push $remote $branch
                Write-Host "Done!" -ForegroundColor Green
            }
            Read-Host "Press Enter"
        }
        "3" {
            Write-Host "Quick: Commit + Push"
            git status --short
            $msg = Read-Host "Commit message"
            if ($msg) {
                git commit -m $msg
                git push $remote $branch
                Write-Host "Done!" -ForegroundColor Green
            }
            Read-Host "Press Enter"
        }
        "4" {
            Write-Host "Pushing to $remote/$branch..."
            git push $remote $branch
            Read-Host "Press Enter"
        }
        "5" {
            Write-Host "Pulling from $remote/$branch..."
            git pull $remote $branch
            Read-Host "Press Enter"
        }
        "6" {
            Write-Host "Force push (safe) to $remote/$branch"
            $confirm = Read-Host "Type YES to confirm"
            if ($confirm -eq "YES") {
                git push --force-with-lease $remote $branch
                Write-Host "Done!" -ForegroundColor Green
            }
            Read-Host "Press Enter"
        }
        "7" {
            Write-Host "Amend last commit"
            git log --oneline -n 1
            $msg = Read-Host "New message (or Enter to keep)"
            if ($msg) {
                git commit --amend -m $msg
            } else {
                git commit --amend --no-edit
            }
            Write-Host "Amended!" -ForegroundColor Green
            Read-Host "Press Enter"
        }
        "8" {
            git log --oneline --graph -n 10
            Read-Host "Press Enter"
        }
        "9" {
            git reset
            Write-Host "Unstaged all files" -ForegroundColor Green
            Read-Host "Press Enter"
        }
        "0" {
            Write-Host "Exiting..."
            exit
        }
        default {
            Write-Host "Invalid choice"
            Read-Host "Press Enter"
        }
    }
}
