# Setup Git and Push to GitHub Repository "G-v1.0"
# This script helps initialize Git repository and push to GitHub

param(
    [string]$GithubUsername = "",
    [switch]$SkipGitCheck
)

Write-Host "`n=== G6 Platform - GitHub Setup Script ===" -ForegroundColor Cyan
Write-Host "This script will help you push the project to GitHub repository 'G-v1.0'`n" -ForegroundColor Yellow

# Check if Git is installed
if (-not $SkipGitCheck) {
    try {
        $gitVersion = git --version 2>$null
        Write-Host "[OK] Git is installed: $gitVersion" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERROR] Git is not installed!" -ForegroundColor Red
        Write-Host "`nPlease install Git first:" -ForegroundColor Yellow
        Write-Host "  1. Download from: https://git-scm.com/download/win" -ForegroundColor White
        Write-Host "  2. Run the installer with default options" -ForegroundColor White
        Write-Host "  3. Restart PowerShell" -ForegroundColor White
        Write-Host "  4. Run this script again`n" -ForegroundColor White
        exit 1
    }
}

# Get GitHub username if not provided
if ([string]::IsNullOrWhiteSpace($GithubUsername)) {
    $GithubUsername = Read-Host "`nEnter your GitHub username"
    if ([string]::IsNullOrWhiteSpace($GithubUsername)) {
        Write-Host "[ERROR] GitHub username is required!" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n=== Step 1: Checking .env file ===" -ForegroundColor Cyan
if (Test-Path ".env") {
    Write-Host "[WARNING] .env file contains sensitive data!" -ForegroundColor Yellow
    Write-Host "The .gitignore file will exclude it from commits." -ForegroundColor Green
    Write-Host "Make sure .env.example is up to date for other users." -ForegroundColor Yellow
}

Write-Host "`n=== Step 2: Initialize Git Repository ===" -ForegroundColor Cyan
if (Test-Path ".git") {
    Write-Host "[INFO] Git repository already initialized" -ForegroundColor Yellow
} else {
    Write-Host "Initializing Git repository..." -ForegroundColor White
    git init
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Git repository initialized" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Failed to initialize Git repository" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n=== Step 3: Configure Git User (if needed) ===" -ForegroundColor Cyan
$gitUserName = git config user.name 2>$null
$gitUserEmail = git config user.email 2>$null

if ([string]::IsNullOrWhiteSpace($gitUserName)) {
    $userName = Read-Host "Enter your name for Git commits"
    git config user.name "$userName"
    Write-Host "[OK] Git user.name set to: $userName" -ForegroundColor Green
}

if ([string]::IsNullOrWhiteSpace($gitUserEmail)) {
    $userEmail = Read-Host "Enter your email for Git commits"
    git config user.email "$userEmail"
    Write-Host "[OK] Git user.email set to: $userEmail" -ForegroundColor Green
}

Write-Host "`n=== Step 4: Add Files to Git ===" -ForegroundColor Cyan
Write-Host "Adding all files (excluding those in .gitignore)..." -ForegroundColor White
git add .
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Files added to staging area" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Failed to add files" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Step 5: Create Initial Commit ===" -ForegroundColor Cyan
$commitMessage = "Initial commit: G6 Options Analytics Platform v1.0

- Multi-index options data collection (NIFTY, BANKNIFTY, FINNIFTY, SENSEX)
- Real-time analytics with IV and Greeks calculation
- CSV storage with dual-sink architecture (CSV + optional InfluxDB)
- Grafana dashboards for visualization (analytics and overlays)
- FastAPI dashboard API for live data streaming
- Comprehensive rate limiting and error handling
- Weekday master overlay system for pattern analysis
"

git commit -m "$commitMessage"
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Initial commit created" -ForegroundColor Green
} else {
    Write-Host "[WARNING] Commit may have failed or nothing to commit" -ForegroundColor Yellow
}

Write-Host "`n=== Step 6: Add GitHub Remote ===" -ForegroundColor Cyan
$remoteUrl = "https://github.com/$GithubUsername/G-v1.0.git"
Write-Host "Remote URL: $remoteUrl" -ForegroundColor White

$existingRemote = git remote get-url origin 2>$null
if ($existingRemote) {
    Write-Host "[INFO] Remote 'origin' already exists: $existingRemote" -ForegroundColor Yellow
    $updateRemote = Read-Host "Update remote URL? (y/n)"
    if ($updateRemote -eq 'y') {
        git remote set-url origin $remoteUrl
        Write-Host "[OK] Remote URL updated" -ForegroundColor Green
    }
} else {
    git remote add origin $remoteUrl
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Remote 'origin' added" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Failed to add remote" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n=== Step 7: Rename Branch to 'main' ===" -ForegroundColor Cyan
$currentBranch = git branch --show-current 2>$null
if ($currentBranch -ne "main") {
    git branch -M main
    Write-Host "[OK] Branch renamed to 'main'" -ForegroundColor Green
} else {
    Write-Host "[INFO] Already on 'main' branch" -ForegroundColor Yellow
}

Write-Host "`n=== Step 8: Push to GitHub ===" -ForegroundColor Cyan
Write-Host "`nIMPORTANT:" -ForegroundColor Yellow
Write-Host "Before pushing, make sure you have created the GitHub repository:" -ForegroundColor Yellow
Write-Host "  1. Go to: https://github.com/new" -ForegroundColor White
Write-Host "  2. Repository name: G-v1.0" -ForegroundColor White
Write-Host "  3. Choose Public or Private" -ForegroundColor White
Write-Host "  4. DO NOT initialize with README, .gitignore, or license" -ForegroundColor Red
Write-Host "  5. Click 'Create repository'`n" -ForegroundColor White

$readyToPush = Read-Host "Have you created the GitHub repository? (y/n)"
if ($readyToPush -eq 'y') {
    Write-Host "`nPushing to GitHub..." -ForegroundColor White
    git push -u origin main
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[SUCCESS] Project pushed to GitHub!" -ForegroundColor Green
        Write-Host "`nRepository URL: https://github.com/$GithubUsername/G-v1.0" -ForegroundColor Cyan
        Write-Host "`nNext steps:" -ForegroundColor Yellow
        Write-Host "  1. Visit your repository on GitHub" -ForegroundColor White
        Write-Host "  2. Add a description and topics" -ForegroundColor White
        Write-Host "  3. Consider adding a LICENSE file" -ForegroundColor White
        Write-Host "  4. Update README.md with any deployment-specific notes`n" -ForegroundColor White
    } else {
        Write-Host "`n[ERROR] Failed to push to GitHub" -ForegroundColor Red
        Write-Host "Common issues:" -ForegroundColor Yellow
        Write-Host "  - Repository doesn't exist on GitHub" -ForegroundColor White
        Write-Host "  - Authentication failed (you may need to set up GitHub CLI or Personal Access Token)" -ForegroundColor White
        Write-Host "  - Network connectivity issues`n" -ForegroundColor White
        
        Write-Host "To authenticate with GitHub, you can:" -ForegroundColor Yellow
        Write-Host "  1. Install GitHub CLI: https://cli.github.com/" -ForegroundColor White
        Write-Host "  2. Or create a Personal Access Token: https://github.com/settings/tokens" -ForegroundColor White
        Write-Host "     Then use: git config credential.helper store`n" -ForegroundColor White
    }
} else {
    Write-Host "`nSetup paused. Create the repository and run this script again.`n" -ForegroundColor Yellow
}

Write-Host "=== Script Completed ===" -ForegroundColor Cyan
