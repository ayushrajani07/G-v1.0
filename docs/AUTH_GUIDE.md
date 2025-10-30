# G6 Platform - Authentication & Token Management Guide

**Complete User Guide for Kite Connect Authentication**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication Flow](#2-authentication-flow)
3. [Token Manager](#3-token-manager)
4. [Token Storage](#4-token-storage)
5. [Token Refresh](#5-token-refresh)
6. [Complete Workflows](#6-complete-workflows)
7. [Configuration Reference](#7-configuration-reference)
8. [Troubleshooting](#8-troubleshooting)
9. [Best Practices](#9-best-practices)
10. [Summary](#10-summary)

---

## 1. Overview

### What is Authentication?

The G6 Platform uses **Kite Connect API** for live market data, requiring:

- **API Key**: Application identifier
- **Access Token**: User-specific session token (valid for 24 hours)

### Authentication Methods

✅ **Interactive Login**: Browser-based OAuth flow  
✅ **Headless Mode**: Pre-generated token from env var  
✅ **Token Refresh**: Auto-detect expiry and re-authenticate  
✅ **Fallback**: Mock provider if auth fails  

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    G6 Application                           │
│  ┌──────────────┐                                           │
│  │ Orchestrator │                                           │
│  └──────┬───────┘                                           │
│         │                                                    │
│         │ requires token                                    │
│         │                                                    │
│  ┌──────▼────────┐                                          │
│  │ KiteProvider  │                                          │
│  │               │                                          │
│  │ 1. Check env  │                                          │
│  │    KITE_ACCESS_TOKEN                                     │
│  │                                                           │
│  │ 2. Load from  │                                          │
│  │    .kite_token                                           │
│  │                                                           │
│  │ 3. Interactive│                                          │
│  │    login      │                                          │
│  └──────┬────────┘                                          │
└─────────┼──────────────────────────────────────────────────┘
          │
          │ (if interactive)
          │
    ┌─────▼──────┐
    │  Browser   │  → Kite Login Page
    │            │  ← Redirect with request_token
    └─────┬──────┘
          │
    ┌─────▼──────┐
    │ Token      │  → Exchange request_token
    │ Manager    │  ← access_token (24h validity)
    │            │
    │ Save to:   │
    │ .kite_token│
    └────────────┘
```

### File Structure

```
src/broker/kite/
├── __init__.py
├── auth.py                  # Auth helpers (is_auth_error, AuthState)
├── client_bootstrap.py      # Client initialization
└── token_manager.py         # Token persistence

src/provider/
├── kite_provider.py         # Kite Connect provider
└── auth.py                  # Provider-level auth wrapper

src/tools/
└── token_manager.py         # CLI tool for token management

.kite_token                  # Token storage (gitignored)
```

---

## 2. Authentication Flow

### OAuth 2.0 Flow

**Step 1: Generate Login URL**

```python
from kiteconnect import KiteConnect

api_key = "your_api_key"
kite = KiteConnect(api_key=api_key)

login_url = kite.login_url()
print(f"Visit: {login_url}")
```

**Step 2: User Login**

User visits URL → Logs into Kite → Redirects to:
```
http://127.0.0.1:5000?request_token=abc123&action=login&status=success
```

**Step 3: Exchange Request Token**

```python
request_token = "abc123"  # From redirect URL
api_secret = "your_api_secret"

data = kite.generate_session(request_token, api_secret=api_secret)
access_token = data["access_token"]
```

**Step 4: Store Token**

```python
import json

with open(".kite_token", "w") as f:
    json.dump({
        "access_token": access_token,
        "generated_at": datetime.now(UTC).isoformat()
    }, f)
```

**Step 5: Use Token**

```python
from kiteconnect import KiteConnect

kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

# Fetch quote
quote = kite.quote("NSE:NIFTY 50")
```

---

## 3. Token Manager

### CLI Tool

**Location**: `src/tools/token_manager.py`

Interactive token acquisition and management.

#### Basic Usage

```bash
# Run token manager
python -m src.tools.token_manager

# Follow prompts:
# 1. Enter API key
# 2. Open browser to login URL
# 3. Paste redirect URL
# 4. Token saved to .kite_token
```

#### Programmatic Usage

```python
from src.tools.token_manager import TokenManager

manager = TokenManager(
    api_key="your_api_key",
    api_secret="your_api_secret",
    token_file=".kite_token"
)

# Interactive login
access_token = manager.get_token()

# Use token
kite = manager.get_kite_client(access_token)
```

### Token Storage Format

**File**: `.kite_token`

```json
{
  "access_token": "abc123def456...",
  "generated_at": "2025-01-25T10:00:00Z",
  "expires_at": "2025-01-26T10:00:00Z"
}
```

**Security**:
- File permissions: `0600` (owner read/write only)
- Gitignored (not committed to repo)
- Ephemeral (24h validity)

---

## 4. Token Storage

### Environment Variable (Highest Priority)

```bash
# Set token in environment
export KITE_ACCESS_TOKEN=your_access_token_here

# Platform uses env var first
python -m src.main
```

**Use Case**: CI/CD, automation, Docker containers

### File Storage (Fallback)

```bash
# Token stored in .kite_token
cat .kite_token

# Platform loads from file if env var not set
python -m src.main
```

**Use Case**: Local development, manual testing

### In-Memory (Ephemeral)

```python
# Provide token at runtime
from src.provider.kite_provider import KiteProvider

provider = KiteProvider(
    api_key="your_api_key",
    access_token="your_access_token"
)
```

**Use Case**: Embedded systems, testing

---

## 5. Token Refresh

### Auto-Refresh Logic

```python
from src.broker.kite.auth import is_auth_error, AuthState

state = AuthState()

try:
    # API call
    quote = kite.quote("NSE:NIFTY 50")
except Exception as e:
    if is_auth_error(e):
        # Token expired, need to re-authenticate
        state.record_error(e)
        
        # Trigger token refresh
        new_token = refresh_token()
        kite.set_access_token(new_token)
```

### is_auth_error() Function

**Location**: `src/broker/kite/auth.py`

```python
def is_auth_error(exc: BaseException) -> bool:
    """Detect authentication errors from exception."""
    try:
        msg = str(exc).lower()
    except Exception:
        return False
    
    return any(keyword in msg for keyword in [
        "token expired",
        "invalid token",
        "unauthorized",
        "authentication failed",
        "permission denied",
    ])
```

**Usage**:
```python
from src.broker.kite.auth import is_auth_error

try:
    data = kite.quote("NSE:NIFTY 50")
except Exception as e:
    if is_auth_error(e):
        print("Auth error detected, need new token")
        # Trigger re-auth
    else:
        print(f"Other error: {e}")
```

---

## 6. Complete Workflows

### Workflow 1: First-Time Setup

**Scenario**: New user setting up authentication.

#### Step 1: Get API Credentials

1. Visit https://kite.zerodha.com/
2. Go to **Console** → **Apps** → **Create new app**
3. Copy **API Key** and **API Secret**

#### Step 2: Set API Credentials

```bash
# Set in environment
export KITE_API_KEY=your_api_key
export KITE_API_SECRET=your_api_secret
```

Or create `config/kite_credentials.json`:
```json
{
  "api_key": "your_api_key",
  "api_secret": "your_api_secret"
}
```

#### Step 3: Run Token Manager

```bash
python -m src.tools.token_manager

# Output:
# Kite Token Manager
# ==================
# API Key: your_api_key
# 
# Login URL: https://kite.zerodha.com/connect/login?v=3&api_key=...
# 
# 1. Open URL in browser
# 2. Login to Kite
# 3. Paste redirect URL here:
```

#### Step 4: Complete Login

1. Open login URL in browser
2. Enter Kite credentials
3. Copy redirect URL from browser (e.g., `http://127.0.0.1:5000?request_token=abc123`)
4. Paste in terminal

**Output**:
```
Access Token: abc123def456...
Saved to: .kite_token
```

#### Step 5: Verify Token

```bash
# Check token file
cat .kite_token

# Test with platform
python -m src.main

# Expected:
# INFO - Provider: kite_live
# INFO - Auth: valid (expires 2025-01-26T10:00:00Z)
```

---

### Workflow 2: Headless Authentication

**Scenario**: Automated system (CI/CD, server) without browser.

#### Step 1: Generate Token Manually

On a machine with browser:
```bash
python -m src.tools.token_manager
```

#### Step 2: Copy Token

```bash
cat .kite_token
# Output: {"access_token": "abc123...", ...}
```

#### Step 3: Set on Server

```bash
# On server (no browser)
export KITE_ACCESS_TOKEN=abc123...

# Start platform
python -m src.main
```

Or copy `.kite_token` file:
```bash
scp .kite_token server:/app/.kite_token
```

---

### Workflow 3: Handle Token Expiry

**Scenario**: Platform running overnight, token expires.

#### Step 1: Detect Expiry

```python
from src.broker.kite.auth import is_auth_error

try:
    quote = kite.quote("NSE:NIFTY 50")
except Exception as e:
    if is_auth_error(e):
        print("Token expired!")
        # Trigger refresh
```

#### Step 2: Fallback to Mock

```python
from src.provider.mock_provider import MockProvider

# If auth fails, switch to mock
if is_auth_error(error):
    print("Falling back to mock provider")
    provider = MockProvider()
```

#### Step 3: Re-authenticate

**Manual**:
```bash
# Generate new token
python -m src.tools.token_manager

# Restart platform
python -m src.main
```

**Automated** (if using refresh token - not supported by Kite):
```python
# Kite doesn't support refresh tokens
# Must re-authenticate interactively every 24h
```

---

### Workflow 4: Multiple Users/Accounts

**Scenario**: Different tokens for different environments.

#### Step 1: Create Token Files

```bash
# Development
python -m src.tools.token_manager
mv .kite_token .kite_token.dev

# Production
python -m src.tools.token_manager
mv .kite_token .kite_token.prod
```

#### Step 2: Set Token Path

```bash
# Development
export G6_KITE_TOKEN_FILE=.kite_token.dev
python -m src.main

# Production
export G6_KITE_TOKEN_FILE=.kite_token.prod
python -m src.main
```

---

## 7. Configuration Reference

### Environment Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `KITE_API_KEY` | string | ` ` | Kite Connect API key |
| `KITE_API_SECRET` | string | ` ` | Kite Connect API secret |
| `KITE_ACCESS_TOKEN` | string | ` ` | Pre-generated access token |
| `G6_KITE_TOKEN_FILE` | string | `.kite_token` | Token storage file path |
| `G6_PROVIDER` | string | `kite_live` | Primary provider |
| `G6_PROVIDER_FALLBACK` | string | `mock` | Fallback if auth fails |

### Token File Schema

```json
{
  "access_token": "string (required)",
  "generated_at": "ISO 8601 timestamp",
  "expires_at": "ISO 8601 timestamp (generated_at + 24h)",
  "api_key": "string (optional)",
  "user_id": "string (optional)"
}
```

---

## 8. Troubleshooting

### Issue 1: Invalid API Key

**Symptom**: `Invalid API credentials`

**Cause**: Wrong or expired API key.

**Fix**:
```bash
# Verify API key
echo $KITE_API_KEY

# Get from Kite Console
# https://kite.zerodha.com/apps
```

### Issue 2: Token Expired

**Symptom**: `Token is invalid or has expired`

**Cause**: Access token older than 24 hours.

**Fix**:
```bash
# Generate new token
python -m src.tools.token_manager

# Or set new token
export KITE_ACCESS_TOKEN=new_token
```

### Issue 3: Redirect URL Not Working

**Symptom**: Browser shows "This site can't be reached"

**Cause**: Redirect URL `http://127.0.0.1:5000` not whitelisted in Kite app settings.

**Fix**:
1. Go to Kite Console → Apps → Your App
2. Add redirect URL: `http://127.0.0.1:5000`
3. Save
4. Try login again

### Issue 4: Permission Denied

**Symptom**: `FileNotFoundError: [Errno 13] Permission denied: '.kite_token'`

**Cause**: File permissions too restrictive.

**Fix**:
```bash
# Make file writable
chmod 600 .kite_token

# Or delete and regenerate
rm .kite_token
python -m src.tools.token_manager
```

---

## 9. Best Practices

### DO ✅

1. **Use environment variables for production**
   ```bash
   # Good: env var in CI/CD
   export KITE_ACCESS_TOKEN=$(cat .kite_token | jq -r .access_token)
   
   # Bad: commit token file
   git add .kite_token
   ```

2. **Set restrictive file permissions**
   ```bash
   # Good: owner-only
   chmod 600 .kite_token
   
   # Bad: world-readable
   chmod 644 .kite_token
   ```

3. **Gitignore token files**
   ```bash
   # .gitignore
   .kite_token
   .kite_token.*
   ```

4. **Validate token before use**
   ```python
   # Good: test auth
   try:
       profile = kite.profile()
       print(f"Authenticated as: {profile['user_id']}")
   except Exception as e:
       if is_auth_error(e):
           print("Token invalid, need to re-auth")
   
   # Bad: assume valid
   quote = kite.quote("NSE:NIFTY 50")  # May crash
   ```

5. **Handle expiry gracefully**
   ```python
   # Good: fallback to mock
   try:
       provider = KiteProvider()
   except AuthError:
       provider = MockProvider()
   
   # Bad: crash
   provider = KiteProvider()  # Raises if no token
   ```

### DON'T ❌

1. **Don't commit secrets**
   ```bash
   # Bad
   git add config/kite_credentials.json
   
   # Good
   echo "config/kite_credentials.json" >> .gitignore
   ```

2. **Don't hardcode tokens**
   ```python
   # Bad
   access_token = "abc123..."
   
   # Good
   access_token = os.getenv("KITE_ACCESS_TOKEN")
   ```

3. **Don't share tokens**
   ```bash
   # Bad: send .kite_token via email
   
   # Good: each user generates their own token
   ```

4. **Don't skip error handling**
   ```python
   # Bad: crash on auth failure
   kite = KiteConnect(api_key)
   kite.set_access_token(token)
   quote = kite.quote("NSE:NIFTY 50")
   
   # Good: handle errors
   try:
       kite = KiteConnect(api_key)
       kite.set_access_token(token)
       quote = kite.quote("NSE:NIFTY 50")
   except Exception as e:
       if is_auth_error(e):
           # Re-authenticate
           pass
       else:
           raise
   ```

---

## 10. Summary

### Quick Start

```bash
# 1. Get API credentials from Kite Console
# https://kite.zerodha.com/apps

# 2. Set API key/secret
export KITE_API_KEY=your_api_key
export KITE_API_SECRET=your_api_secret

# 3. Generate token
python -m src.tools.token_manager

# 4. Start platform
python -m src.main

# Platform will use token from .kite_token file
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **API Key** | Application identifier (public) |
| **API Secret** | Application secret (private) |
| **Request Token** | One-time code from OAuth redirect |
| **Access Token** | 24-hour session token |
| **Token File** | Persistent storage (.kite_token) |
| **is_auth_error()** | Detect authentication failures |

### VS Code Task

```bash
# Run token manager
Task: "Auth: Kite Login/Refresh"

# Or manually:
python -m src.tools.token_manager
```

### Related Guides

- **[Collector System Guide](COLLECTOR_SYSTEM_GUIDE.md)**: Provider selection
- **[Configuration Guide](CONFIGURATION_GUIDE.md)**: Auth configuration
- **[Testing Guide](TESTING_GUIDE.md)**: Mock provider for testing

---

**End of Auth Guide**
