# Quick Start Guide: Push G6 Project to GitHub

## Prerequisites
1. **Install Git**
   - Download: https://git-scm.com/download/win
   - Install with default options
   - Restart PowerShell after installation

2. **Create GitHub Account** (if you don't have one)
   - Sign up at: https://github.com/join

## Step-by-Step Instructions

### 1. Install Git (if not already installed)
```powershell
# Check if Git is installed
git --version

# If not installed, download and install from:
# https://git-scm.com/download/win
```

### 2. Create GitHub Repository
1. Go to: https://github.com/new
2. Repository name: **G-v1.0**
3. Description (optional): "G6 Options Analytics Platform - Multi-index options data collection and analysis"
4. Choose **Public** or **Private**
5. ⚠️ **DO NOT** check:
   - Add a README file
   - Add .gitignore
   - Choose a license
6. Click **"Create repository"**

### 3. Run the Setup Script
```powershell
# Navigate to project directory
cd C:\Users\Asus\Desktop\g6_reorganized

# Run the automated setup script
.\setup_git_and_push.ps1 -GithubUsername "YOUR_GITHUB_USERNAME"
```

Replace `YOUR_GITHUB_USERNAME` with your actual GitHub username.

### 4. Authenticate with GitHub
When prompted to authenticate, you have two options:

**Option A: GitHub CLI (Recommended)**
```powershell
# Install GitHub CLI
winget install --id GitHub.cli

# Authenticate
gh auth login
```

**Option B: Personal Access Token**
1. Go to: https://github.com/settings/tokens
2. Click "Generate new token (classic)"
3. Select scopes: `repo` (all)
4. Copy the token
5. When Git prompts for password, paste the token

### 5. Verify Upload
Visit: `https://github.com/YOUR_USERNAME/G-v1.0`

## Manual Method (Alternative)

If you prefer to run commands manually:

```powershell
# Initialize Git repository
git init

# Configure Git user (first time only)
git config user.name "Your Name"
git config user.email "your.email@example.com"

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: G6 Options Analytics Platform v1.0"

# Add GitHub remote (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/G-v1.0.git

# Rename branch to main
git branch -M main

# Push to GitHub
git push -u origin main
```

## Important Notes

### Security
- ✅ `.env` file is excluded (contains sensitive API keys)
- ✅ `.env.example` is included (template for others)
- ✅ Data directories are excluded
- ✅ Logs and temporary files are excluded

### Files Included
- ✅ Source code (`src/`, `scripts/`)
- ✅ Configuration files (`config/`)
- ✅ Documentation (README.md, etc.)
- ✅ Requirements (`requirements.txt`)
- ✅ Grafana dashboard definitions
- ✅ PowerShell scripts

### Files Excluded (by .gitignore)
- ❌ `.env` (sensitive credentials)
- ❌ `data/` (CSV files, runtime data)
- ❌ `logs/` (log files)
- ❌ `__pycache__/` (Python cache)
- ❌ `.vscode/` (IDE settings)

## Troubleshooting

### Error: "Git is not recognized"
- Install Git and restart PowerShell
- Verify installation: `git --version`

### Error: "Repository not found"
- Make sure you created the repository on GitHub first
- Check the repository name is exactly "G-v1.0"
- Verify your GitHub username is correct

### Error: "Authentication failed"
- Use GitHub CLI: `gh auth login`
- Or create Personal Access Token (see Option B above)

### Error: "Permission denied"
- Check repository is created under your account
- Verify you have push access to the repository

## Next Steps After Upload

1. **Add Repository Description**
   - Go to repository settings
   - Add description and topics (e.g., "python", "trading", "options", "analytics")

2. **Add LICENSE**
   - Choose appropriate license (MIT, GPL, etc.)
   - Add LICENSE file to repository

3. **Enable GitHub Actions** (optional)
   - Set up CI/CD for automated testing
   - Configure automated deployments

4. **Protect Main Branch** (recommended)
   - Require pull request reviews
   - Require status checks to pass

5. **Add Collaborators** (if needed)
   - Settings → Collaborators
   - Invite team members

## Support

If you encounter issues:
1. Check the error messages in the PowerShell output
2. Verify all prerequisites are met
3. Consult GitHub documentation: https://docs.github.com/

---

**Happy coding! 🚀**
