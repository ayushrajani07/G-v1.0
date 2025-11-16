# 🚀 Quick Reference: Push to GitHub

## One-Line Commands (After Git Installation)

### Automated Method (Recommended)
```powershell
.\setup_git_and_push.ps1 -GithubUsername "YOUR_USERNAME"
```

### Manual Method
```powershell
git init; git add .; git commit -m "Initial commit: G6 v1.0"; git remote add origin https://github.com/YOUR_USERNAME/G-v1.0.git; git branch -M main; git push -u origin main
```

## GitHub Repository Creation
1. Visit: https://github.com/new
2. Name: **G-v1.0**
3. **DON'T** initialize with README/gitignore/license
4. Click "Create repository"

## Authentication Options

### GitHub CLI (Easiest)
```powershell
winget install --id GitHub.cli
gh auth login
```

### Personal Access Token
1. Create: https://github.com/settings/tokens
2. Scopes: Select "repo" (all)
3. Use token as password when Git prompts

## Files Status
| File/Folder | Status | Notes |
|-------------|--------|-------|
| `.env` | ❌ Excluded | Your secrets are safe |
| `.env.example` | ✅ Included | Template for others |
| `src/` | ✅ Included | All source code |
| `data/` | ❌ Excluded | Runtime data |
| `README.md` | ✅ Included | Documentation |
| `.gitignore` | ✅ Included | Git exclusions |

## Verify Upload
After pushing, check:
```
https://github.com/YOUR_USERNAME/G-v1.0
```

## Need Help?
- 📖 Read: `GITHUB_SETUP.md`
- ✅ Check: `PRE_PUSH_CHECKLIST.md`
- 💾 Backup: `.env.backup`

## Common Issues

**"Git not found"** → Install Git, restart PowerShell

**"Authentication failed"** → Use GitHub CLI or Personal Access Token

**"Repository not found"** → Create repository on GitHub first

---
**All set! Run the setup script when ready! 🎯**
