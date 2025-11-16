#!/usr/bin/env pwsh
# Git Operations Menu for G6 Project
# Provides common git workflows with error handling

function Show-Menu {
    Clear-Host
    Write-Host "================================" -ForegroundColor Cyan
    Write-Host "   Git Operations Menu" -ForegroundColor Cyan
    Write-Host "================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Status & Info:" -ForegroundColor Yellow
    Write-Host "  1. Show status"
    Write-Host "  2. Show branch info"
    Write-Host "  3. Show last 5 commits"
    Write-Host "  4. Show changed files"
    Write-Host ""
    Write-Host "Basic Operations:" -ForegroundColor Yellow
    Write-Host "  5. Add all changes (git add -A)"
    Write-Host "  6. Add specific file"
    Write-Host "  7. Commit (with message)"
    Write-Host "  8. Add + Commit (combined)"
    Write-Host ""
    Write-Host "Push/Pull Operations:" -ForegroundColor Yellow
    Write-Host "  9. Push to current branch"
    Write-Host " 10. Pull from current branch"
    Write-Host " 11. Push --force-with-lease (safe force)"
    Write-Host " 12. Push --force (dangerous!)"
    Write-Host ""
    Write-Host "Sync Operations:" -ForegroundColor Yellow
    Write-Host " 13. Full sync (add + commit + push)"
    Write-Host " 14. Quick commit + push (skip add)"
    Write-Host " 15. Amend last commit + force push"
    Write-Host ""
    Write-Host "Branch Operations:" -ForegroundColor Yellow
    Write-Host " 16. Create new branch"
    Write-Host " 17. Switch branch"
    Write-Host " 18. Merge branch into current"
    Write-Host " 19. Rebase current on main"
    Write-Host ""
    Write-Host "Recovery & Reset:" -ForegroundColor Yellow
    Write-Host " 20. Unstage all (git reset)"
    Write-Host " 21. Discard all changes (DANGER)"
    Write-Host " 22. Undo last commit (keep changes)"
    Write-Host " 23. Hard reset to origin (DANGER)"
    Write-Host ""
    Write-Host "Advanced:" -ForegroundColor Yellow
    Write-Host " 24. Stash changes"
    Write-Host " 25. Pop stash"
    Write-Host " 26. Cherry-pick commit"
    Write-Host " 27. Interactive rebase"
    Write-Host ""
    Write-Host " 28. Progress check (exception count)"
    Write-Host ""
    Write-Host "  0. Exit" -ForegroundColor Red
    Write-Host ""
}

function Get-CurrentBranch {
    return git rev-parse --abbrev-ref HEAD 2>$null
}

function Get-RemoteName {
    $remote = git remote 2>$null | Select-Object -First 1
    if ($remote) { return $remote } else { return "origin" }
}

# Status & Info
function Show-Status {
    Write-Host "`n=== Git Status ===" -ForegroundColor Cyan
    git status
    Write-Host ""
}

function Show-BranchInfo {
    Write-Host "`n=== Branch Information ===" -ForegroundColor Cyan
    $branch = Get-CurrentBranch
    $remote = Get-RemoteName
    Write-Host "Current branch: $branch" -ForegroundColor Green
    Write-Host "Remote: $remote" -ForegroundColor Green
    Write-Host ""
    Write-Host "All branches:" -ForegroundColor Yellow
    git branch -a
    Write-Host ""
}

function Show-RecentCommits {
    Write-Host "`n=== Last 5 Commits ===" -ForegroundColor Cyan
    git log --oneline --graph --decorate -n 5
    Write-Host ""
}

function Show-ChangedFiles {
    Write-Host "`n=== Changed Files ===" -ForegroundColor Cyan
    git diff --name-status
    Write-Host ""
}

# Basic Operations
function Add-AllChanges {
    Write-Host "`n=== Adding all changes ===" -ForegroundColor Cyan
    git add -A
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ All changes staged" -ForegroundColor Green
        git status --short
    } else {
        Write-Host "✗ Failed to add changes" -ForegroundColor Red
    }
    Write-Host ""
}

function Add-SpecificFile {
    Write-Host "`n=== Add Specific File ===" -ForegroundColor Cyan
    git status --short
    Write-Host ""
    $file = Read-Host "Enter file path"
    if ($file) {
        git add $file
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ File staged: $file" -ForegroundColor Green
        } else {
            Write-Host "✗ Failed to add file" -ForegroundColor Red
        }
    }
    Write-Host ""
}

function Commit-Changes {
    Write-Host "`n=== Commit Changes ===" -ForegroundColor Cyan
    git status --short
    Write-Host ""
    $message = Read-Host "Enter commit message"
    if ($message) {
        git commit -m $message
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Committed successfully" -ForegroundColor Green
        } else {
            Write-Host "✗ Commit failed" -ForegroundColor Red
        }
    } else {
        Write-Host "Cancelled - no message provided" -ForegroundColor Yellow
    }
    Write-Host ""
}

function Add-AndCommit {
    Write-Host "`n=== Add + Commit ===" -ForegroundColor Cyan
    git status --short
    Write-Host ""
    $message = Read-Host "Enter commit message"
    if ($message) {
        git add -A
        git commit -m $message
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Added and committed successfully" -ForegroundColor Green
        } else {
            Write-Host "✗ Operation failed" -ForegroundColor Red
        }
    } else {
        Write-Host "Cancelled - no message provided" -ForegroundColor Yellow
    }
    Write-Host ""
}

# Push/Pull Operations
function Push-ToRemote {
    Write-Host "`n=== Pushing to remote ===" -ForegroundColor Cyan
    $branch = Get-CurrentBranch
    $remote = Get-RemoteName
    Write-Host "Pushing $branch to $remote..." -ForegroundColor Yellow
    git push $remote $branch
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Push successful" -ForegroundColor Green
    } else {
        Write-Host "✗ Push failed" -ForegroundColor Red
        Write-Host "Hint: Try 'git pull' first or use force-with-lease" -ForegroundColor Yellow
    }
    Write-Host ""
}

function Pull-FromRemote {
    Write-Host "`n=== Pulling from remote ===" -ForegroundColor Cyan
    $branch = Get-CurrentBranch
    $remote = Get-RemoteName
    Write-Host "Pulling $branch from $remote..." -ForegroundColor Yellow
    git pull $remote $branch
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Pull successful" -ForegroundColor Green
    } else {
        Write-Host "✗ Pull failed" -ForegroundColor Red
    }
    Write-Host ""
}

function Push-ForceWithLease {
    Write-Host "`n=== Force Push (with lease) ===" -ForegroundColor Cyan
    $branch = Get-CurrentBranch
    $remote = Get-RemoteName
    Write-Host "WARNING: This will force push (safely)" -ForegroundColor Yellow
    $confirm = Read-Host "Type yes to confirm"
    if ($confirm -eq "yes") {
        git push --force-with-lease $remote $branch
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Success: Force push successful" -ForegroundColor Green
        } else {
            Write-Host "Error: Force push failed" -ForegroundColor Red
        }
    } else {
        Write-Host "Cancelled" -ForegroundColor Yellow
    }
    Write-Host ""
}

function Push-Force {
    Write-Host "`n=== FORCE PUSH (DANGEROUS!) ===" -ForegroundColor Red
    $branch = Get-CurrentBranch
    $remote = Get-RemoteName
    Write-Host "⚠️  WARNING: This will OVERWRITE remote history!" -ForegroundColor Red
    Write-Host "Only use if you are absolutely sure!" -ForegroundColor Red
    $confirm = Read-Host "Type FORCE to confirm"
    if ($confirm -eq "FORCE") {
        git push --force $remote $branch
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Force push completed" -ForegroundColor Green
        } else {
            Write-Host "✗ Force push failed" -ForegroundColor Red
        }
    } else {
        Write-Host "Cancelled" -ForegroundColor Yellow
    }
    Write-Host ""
}

# Sync Operations
function Full-Sync {
    Write-Host "`n=== Full Sync (Add + Commit + Push) ===" -ForegroundColor Cyan
    git status --short
    Write-Host ""
    $message = Read-Host "Enter commit message"
    if ($message) {
        $branch = Get-CurrentBranch
        $remote = Get-RemoteName
        
        Write-Host "1/3 Adding changes..." -ForegroundColor Yellow
        git add -A
        
        Write-Host "2/3 Committing..." -ForegroundColor Yellow
        git commit -m $message
        
        Write-Host "3/3 Pushing to $remote/$branch..." -ForegroundColor Yellow
        git push $remote $branch
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Full sync completed!" -ForegroundColor Green
        } else {
            Write-Host "✗ Sync failed at push stage" -ForegroundColor Red
        }
    } else {
        Write-Host "Cancelled - no message provided" -ForegroundColor Yellow
    }
    Write-Host ""
}

function Quick-CommitPush {
    Write-Host "`n=== Quick Commit + Push ===" -ForegroundColor Cyan
    git status --short
    Write-Host ""
    $message = Read-Host "Enter commit message"
    if ($message) {
        $branch = Get-CurrentBranch
        $remote = Get-RemoteName
        
        git commit -m $message
        git push $remote $branch
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Committed and pushed!" -ForegroundColor Green
        } else {
            Write-Host "✗ Operation failed" -ForegroundColor Red
        }
    }
    Write-Host ""
}

function Amend-AndForcePush {
    Write-Host "`n=== Amend Last Commit + Force Push ===" -ForegroundColor Cyan
    Write-Host "This will modify the last commit" -ForegroundColor Yellow
    $message = Read-Host "New commit message (or press Enter to keep existing)"
    
    if ($message) {
        git commit --amend -m $message
    } else {
        git commit --amend --no-edit
    }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Commit amended" -ForegroundColor Green
        $confirm = Read-Host "Force push? (yes/no)"
        if ($confirm -eq "yes") {
            $branch = Get-CurrentBranch
            $remote = Get-RemoteName
            git push --force-with-lease $remote $branch
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✓ Pushed successfully" -ForegroundColor Green
            }
        }
    }
    Write-Host ""
}

# Branch Operations
function New-Branch {
    Write-Host "`n=== Create New Branch ===" -ForegroundColor Cyan
    $name = Read-Host "Enter new branch name"
    if ($name) {
        git checkout -b $name
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Created and switched to branch: $name" -ForegroundColor Green
        }
    }
    Write-Host ""
}

function Switch-Branch {
    Write-Host "`n=== Switch Branch ===" -ForegroundColor Cyan
    git branch
    Write-Host ""
    $name = Read-Host "Enter branch name"
    if ($name) {
        git checkout $name
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Switched to branch: $name" -ForegroundColor Green
        }
    }
    Write-Host ""
}

function Merge-Branch {
    Write-Host "`n=== Merge Branch ===" -ForegroundColor Cyan
    $current = Get-CurrentBranch
    Write-Host "Current branch: $current" -ForegroundColor Green
    git branch
    Write-Host ""
    $source = Read-Host "Enter branch to merge INTO $current"
    if ($source) {
        git merge $source
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Merged $source into $current" -ForegroundColor Green
        }
    }
    Write-Host ""
}

function Rebase-OnMain {
    Write-Host "`n=== Rebase on Main ===" -ForegroundColor Cyan
    $current = Get-CurrentBranch
    Write-Host "This will rebase $current on main" -ForegroundColor Yellow
    $confirm = Read-Host "Continue? (yes/no)"
    if ($confirm -eq "yes") {
        git fetch origin main
        git rebase origin/main
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Rebase successful" -ForegroundColor Green
        } else {
            Write-Host "✗ Rebase failed - may need conflict resolution" -ForegroundColor Red
        }
    }
    Write-Host ""
}

# Recovery & Reset
function Unstage-All {
    Write-Host "`n=== Unstage All Files ===" -ForegroundColor Cyan
    git reset
    Write-Host "✓ All files unstaged" -ForegroundColor Green
    Write-Host ""
}

function Discard-AllChanges {
    Write-Host "`n=== DISCARD ALL CHANGES ===" -ForegroundColor Red
    Write-Host "⚠️  WARNING: This will delete all uncommitted changes!" -ForegroundColor Red
    $confirm = Read-Host "Type DISCARD to confirm"
    if ($confirm -eq "DISCARD") {
        git reset --hard
        git clean -fd
        Write-Host "✓ All changes discarded" -ForegroundColor Green
    } else {
        Write-Host "Cancelled" -ForegroundColor Yellow
    }
    Write-Host ""
}

function Undo-LastCommit {
    Write-Host "`n=== Undo Last Commit (Keep Changes) ===" -ForegroundColor Cyan
    git reset --soft HEAD~1
    Write-Host "✓ Last commit undone, changes kept" -ForegroundColor Green
    Write-Host ""
}

function Reset-ToOrigin {
    Write-Host "`n=== HARD RESET TO ORIGIN ===" -ForegroundColor Red
    Write-Host "⚠️  WARNING: This will DESTROY all local changes!" -ForegroundColor Red
    $branch = Get-CurrentBranch
    $remote = Get-RemoteName
    Write-Host "Will reset to $remote/$branch" -ForegroundColor Yellow
    $confirm = Read-Host "Type RESET to confirm"
    if ($confirm -eq "RESET") {
        git fetch $remote
        git reset --hard "$remote/$branch"
        Write-Host "✓ Reset to $remote/$branch" -ForegroundColor Green
    } else {
        Write-Host "Cancelled" -ForegroundColor Yellow
    }
    Write-Host ""
}

# Advanced
function Stash-Changes {
    Write-Host "`n=== Stash Changes ===" -ForegroundColor Cyan
    $message = Read-Host "Stash message (optional)"
    if ($message) {
        git stash push -m $message
    } else {
        git stash
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Changes stashed" -ForegroundColor Green
    }
    Write-Host ""
}

function Pop-Stash {
    Write-Host "`n=== Pop Stash ===" -ForegroundColor Cyan
    git stash list
    Write-Host ""
    git stash pop
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Stash applied" -ForegroundColor Green
    }
    Write-Host ""
}

function Cherry-Pick {
    Write-Host "`n=== Cherry-pick Commit ===" -ForegroundColor Cyan
    Write-Host "Recent commits:" -ForegroundColor Yellow
    git log --oneline -n 10
    Write-Host ""
    $commit = Read-Host "Enter commit hash"
    if ($commit) {
        git cherry-pick $commit
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Cherry-pick successful" -ForegroundColor Green
        }
    }
    Write-Host ""
}

function Interactive-Rebase {
    Write-Host "`n=== Interactive Rebase ===" -ForegroundColor Cyan
    $count = Read-Host "How many commits back? (e.g., 3)"
    if ($count) {
        git rebase -i HEAD~$count
    }
    Write-Host ""
}

function Check-Progress {
    Write-Host "`n=== Exception Handler Progress ===" -ForegroundColor Cyan
    try {
        $total = 3244
        $remaining = (Get-ChildItem -Path "src" -Filter "*.py" -Recurse -ErrorAction Stop | 
                     Select-String -Pattern "except Exception:" -AllMatches).Matches.Count
        $fixed = $total - $remaining
        $percent = [math]::Round(($fixed / $total) * 100, 1)
        
        Write-Host "Total handlers: $total" -ForegroundColor White
        Write-Host "Fixed: $fixed" -ForegroundColor Green
        Write-Host "Remaining: $remaining" -ForegroundColor Yellow
        Write-Host "Progress: $percent%" -ForegroundColor Cyan
    } catch {
        Write-Host "Could not calculate progress" -ForegroundColor Red
    }
    Write-Host ""
}

# Main loop
while ($true) {
    Show-Menu
    $choice = Read-Host "Enter choice (0-28)"
    
    switch ($choice) {
        "1" { Show-Status }
        "2" { Show-BranchInfo }
        "3" { Show-RecentCommits }
        "4" { Show-ChangedFiles }
        "5" { Add-AllChanges }
        "6" { Add-SpecificFile }
        "7" { Commit-Changes }
        "8" { Add-AndCommit }
        "9" { Push-ToRemote }
        "10" { Pull-FromRemote }
        "11" { Push-ForceWithLease }
        "12" { Push-Force }
        "13" { Full-Sync }
        "14" { Quick-CommitPush }
        "15" { Amend-AndForcePush }
        "16" { New-Branch }
        "17" { Switch-Branch }
        "18" { Merge-Branch }
        "19" { Rebase-OnMain }
        "20" { Unstage-All }
        "21" { Discard-AllChanges }
        "22" { Undo-LastCommit }
        "23" { Reset-ToOrigin }
        "24" { Stash-Changes }
        "25" { Pop-Stash }
        "26" { Cherry-Pick }
        "27" { Interactive-Rebase }
        "28" { Check-Progress }
        "0" { 
            Write-Host "`nExiting..." -ForegroundColor Cyan
            exit 
        }
        default { 
            Write-Host "`nInvalid choice. Press Enter to continue..." -ForegroundColor Red
        }
    }
    
    Read-Host "Press Enter to continue"
}
