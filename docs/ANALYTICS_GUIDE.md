# Analytics & Greeks - Complete User Guide

## Overview

The **Analytics System** provides comprehensive options analytics including implied volatility calculation, Greek computations, Put-Call Ratio (PCR), market breadth analysis, and volatility surface construction. This is the mathematical engine that powers trading insights in the G6 platform.

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    ANALYTICS PIPELINE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────┐     │
│  │ OPTION DATA  │────▶│   ANALYTICS  │────▶│   METRICS   │     │
│  │              │     │              │     │             │     │
│  │ • Spot Price │     │ • IV Solver  │     │ • PCR       │     │
│  │ • Strikes    │     │ • Greeks     │     │ • Breadth   │     │
│  │ • Premiums   │     │ • BS Pricing │     │ • Vol Surf  │     │
│  │ • OI/Volume  │     │ • Analytics  │     │ • Summary   │     │
│  └──────────────┘     └──────────────┘     └─────────────┘     │
│         │                     │                     │            │
│         │                     │                     │            │
│         ▼                     ▼                     ▼            │
│  Market Data           Black-Scholes          Trading Signals    │
│  (Live/Historical)     Newton-Raphson         Risk Metrics       │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Option Greeks Calculator

### What are Greeks?

Greeks measure the sensitivity of option prices to various factors:
- **Delta (Δ)**: Price sensitivity to underlying movement
- **Gamma (Γ)**: Rate of change of Delta
- **Theta (Θ)**: Time decay (per day)
- **Vega (ν)**: Sensitivity to volatility changes
- **Rho (ρ)**: Sensitivity to interest rate changes

### OptionGreeks Class

**File:** `src/analytics/option_greeks.py`

#### Initialization

```python
from src.analytics.option_greeks import OptionGreeks

# Create calculator with default settings
greeks_calc = OptionGreeks(
    risk_free_rate=0.05,      # 5% annual rate (Indian market)
    use_actual_dte=True        # Calculate precise time to expiry
)

# Custom risk-free rate
greeks_calc = OptionGreeks(risk_free_rate=0.065)  # 6.5% rate
```

**Parameters:**
- `risk_free_rate`: Annual risk-free interest rate (default 5%)
- `use_actual_dte`: Use actual days to expiry vs simplified calculation

#### Black-Scholes Pricing

Calculate theoretical option price and all Greeks in one call:

```python
from datetime import datetime, date

# Calculate for a NIFTY call option
result = greeks_calc.black_scholes(
    is_call=True,              # True for Call, False for Put
    S=23450.0,                 # Spot price (NIFTY at 23450)
    K=23500.0,                 # Strike price
    T=0.0822,                  # Time to expiry (30 days = ~0.0822 years)
    sigma=0.15,                # Volatility (15%)
    r=0.05,                    # Risk-free rate (optional, uses default)
    q=0.0                      # Dividend yield (0 for indices)
)

# Access results
print(f"Theoretical Price: ₹{result['price']:.2f}")
print(f"Delta: {result['delta']:.4f}")
print(f"Gamma: {result['gamma']:.6f}")
print(f"Theta: ₹{result['theta']:.2f} per day")
print(f"Vega: ₹{result['vega']:.2f} per 1% vol change")
print(f"Rho: ₹{result['rho']:.2f} per 1% rate change")
```

**Output Example:**
```
Theoretical Price: ₹112.50
Delta: 0.4523
Gamma: 0.000089
Theta: ₹-5.23 per day
Vega: ₹18.45 per 1% vol change
Rho: ₹8.12 per 1% rate change
```

#### Using Date Objects

Instead of calculating time-to-expiry manually, pass expiry date:

```python
from datetime import date

# Using expiry date (auto-calculates DTE)
result = greeks_calc.black_scholes(
    is_call=True,
    S=23450.0,
    K=23500.0,
    T=date(2025, 11, 28),      # Expiry date
    sigma=0.15,
    current_date=date(2025, 10, 25)  # Current date (optional, defaults to today)
)
```

**Expiry Time Convention:**
- Options expire at **15:30 IST** (3:30 PM) on expiry date
- Same-day expiry properly handles intraday time remaining
- Prevents division by zero for expired options

#### Put Option Greeks

```python
# Calculate for a NIFTY put option
result = greeks_calc.black_scholes(
    is_call=False,             # Put option
    S=23450.0,
    K=23400.0,                 # Strike below spot (ITM put)
    T=0.0822,
    sigma=0.18,                # Puts often have higher IV
    q=0.0
)

print(f"Put Price: ₹{result['price']:.2f}")
print(f"Delta: {result['delta']:.4f}")  # Negative for puts
```

### Time to Expiry Calculation

**Method:** `_calculate_dte()`

```python
from datetime import date

# Calculate days to expiry
dte_years = OptionGreeks._calculate_dte(
    expiry_date=date(2025, 11, 28),
    current_date=date(2025, 10, 25)
)

print(f"Time to expiry: {dte_years:.4f} years")
print(f"Days to expiry: {dte_years * 365:.1f} days")
```

**Features:**
- Handles same-day expiry correctly
- Returns 0.0 for expired options (prevents errors)
- Accounts for intraday time remaining
- Timezone-aware calculations (UTC internally)

### Intrinsic Value (Expired Options)

For expired or near-expired options, use intrinsic value:

```python
# Expired ITM call
result = greeks_calc._intrinsic_value(
    is_call=True,
    S=23500.0,
    K=23400.0
)

print(f"Intrinsic Value: ₹{result['price']:.2f}")  # 100.00
print(f"Delta: {result['delta']:.2f}")              # 1.00 (deep ITM)

# Expired OTM put
result = greeks_calc._intrinsic_value(
    is_call=False,
    S=23500.0,
    K=23400.0
)

print(f"Intrinsic Value: ₹{result['price']:.2f}")  # 0.00 (worthless)
print(f"Delta: {result['delta']:.2f}")              # 0.00
```

---

## Part 2: Implied Volatility (IV) Solver

### What is Implied Volatility?

Implied Volatility (IV) is the market's expectation of future volatility derived from option prices. Unlike historical volatility (calculated from past prices), IV is **forward-looking** and embedded in option premiums.

### Newton-Raphson IV Solver

**Method:** `implied_volatility()`

Uses Newton-Raphson iterative method to reverse-engineer IV from market prices.

#### Basic Usage

```python
# Calculate IV from market price
iv = greeks_calc.implied_volatility(
    is_call=True,
    S=23450.0,                 # Spot price
    K=23500.0,                 # Strike
    T=0.0822,                  # Time to expiry
    market_price=112.50,       # Actual market price
    r=0.05,
    q=0.0
)

print(f"Implied Volatility: {iv*100:.2f}%")  # 15.23%
```

#### Advanced Parameters

```python
# Solve with custom constraints
iv = greeks_calc.implied_volatility(
    is_call=True,
    S=23450.0,
    K=23500.0,
    T=date(2025, 11, 28),
    market_price=112.50,
    precision=0.00001,         # Convergence threshold (0.001% IV)
    max_iterations=100,        # Max solver iterations
    min_iv=0.01,              # Minimum IV (1%)
    max_iv=5.0,               # Maximum IV (500%)
    return_iterations=False    # Return (iv, iterations) tuple
)
```

**Parameters:**
- `precision`: Convergence threshold (default 0.00001)
- `max_iterations`: Maximum Newton-Raphson iterations (default 100)
- `min_iv`: Lower bound for IV (default 1%)
- `max_iv`: Upper bound for IV (default 500%)
- `return_iterations`: Return tuple with iteration count (for monitoring)

#### Monitoring Solver Performance

```python
# Get solver metrics
iv, iterations = greeks_calc.implied_volatility(
    is_call=True,
    S=23450.0,
    K=23500.0,
    T=0.0822,
    market_price=112.50,
    return_iterations=True     # Returns (iv, iterations) tuple
)

print(f"IV: {iv*100:.2f}%")
print(f"Converged in {iterations} iterations")

# Emit metrics for monitoring
from src.metrics import metrics
metrics.iv_solver_iterations.observe(iterations)
metrics.iv_convergence_rate.inc() if iterations < 20 else metrics.iv_slow_convergence.inc()
```

### IV Calculation Edge Cases

#### Case 1: Deep ITM Options

```python
# Deep ITM call (low time value)
iv = greeks_calc.implied_volatility(
    is_call=True,
    S=23500.0,
    K=23000.0,                 # 500 points ITM
    T=0.0274,                  # 10 days
    market_price=505.0         # Mostly intrinsic value
)

print(f"Deep ITM IV: {iv*100:.2f}%")  # May be lower, harder to solve
```

#### Case 2: Near Expiry

```python
# Same-day expiry
iv = greeks_calc.implied_volatility(
    is_call=True,
    S=23450.0,
    K=23500.0,
    T=date(2025, 10, 25),      # Today (expires 15:30)
    market_price=5.0,           # Low premium
    current_date=datetime(2025, 10, 25, 14, 0, 0)  # 2:00 PM
)

# Returns minimum IV if cannot solve
print(f"Near-expiry IV: {iv*100:.2f}%")
```

#### Case 3: Zero or Negative Prices

```python
# Worthless option
iv = greeks_calc.implied_volatility(
    is_call=True,
    S=23450.0,
    K=24000.0,                 # Far OTM
    T=0.0082,                  # 3 days
    market_price=0.05          # Nearly worthless
)

# Returns min_iv (1%) to avoid errors
print(f"OTM IV: {iv*100:.2f}%")  # 1.00%
```

### IV Solver Algorithm

**Newton-Raphson Method:**

```
1. Start with initial guess: σ = 0.3 (30%)
2. Calculate theoretical price using Black-Scholes
3. Find difference: diff = BS_price - market_price
4. Calculate vega (∂price/∂σ)
5. Update: σ_new = σ_old - (diff / vega)
6. Repeat until |diff| < precision
7. Clamp σ within [min_iv, max_iv] each iteration
```

**Convergence Criteria:**
- `|BS_price - market_price| < precision`
- OR `iterations >= max_iterations`

**Typical Performance:**
- ATM options: 5-10 iterations
- ITM/OTM options: 10-20 iterations
- Edge cases: up to 100 iterations (or fail to converge)

---

## Part 3: Option Chain Analytics

### OptionChainAnalytics Class

**File:** `src/analytics/option_chain.py`

Provides advanced analytics for complete option chains.

#### Initialization

```python
from src.analytics.option_chain import OptionChainAnalytics
from src.broker.kite_provider import KiteProvider

# Initialize with provider
provider = KiteProvider()
chain_analytics = OptionChainAnalytics(provider=provider)
```

#### Fetch Option Chain

```python
from datetime import date

# Fetch complete option chain for NIFTY
chain_df = chain_analytics.fetch_option_chain(
    index_symbol="NIFTY",
    expiry_date=date(2025, 11, 28),
    strike_range=(23000.0, 24000.0),  # Min and max strikes
    strike_step=50.0                   # Strike interval (optional, auto-detected)
)

print(f"Fetched {len(chain_df)} option contracts")
print(chain_df.head())
```

**DataFrame Columns:**
```python
# chain_df contains:
- symbol           # Trading symbol
- strike           # Strike price
- expiry           # Expiry date
- type             # "CE" (Call) or "PE" (Put)
- last_price       # Last traded price
- volume           # Volume traded
- buy_quantity     # Bid size
- sell_quantity    # Ask size
- oi               # Open Interest
- change           # Price change
- bid              # Best bid price
- ask              # Best ask price
```

**Auto Strike Step Detection:**

```python
# Automatically determines strike step based on index
# NIFTY: 50
# BANKNIFTY: 100
# FINNIFTY: 50
# SENSEX: 100

chain_df = chain_analytics.fetch_option_chain(
    index_symbol="BANKNIFTY",
    expiry_date=date(2025, 11, 28),
    strike_range=(50000.0, 52000.0)
    # strike_step auto-detected as 100
)
```

#### Calculate Put-Call Ratio (PCR)

```python
# Calculate PCR from option chain
def calculate_pcr(chain_df):
    calls = chain_df[chain_df['type'] == 'CE']
    puts = chain_df[chain_df['type'] == 'PE']
    
    pcr_oi = puts['oi'].sum() / calls['oi'].sum() if calls['oi'].sum() > 0 else 0
    pcr_volume = puts['volume'].sum() / calls['volume'].sum() if calls['volume'].sum() > 0 else 0
    
    return {
        'pcr_oi': pcr_oi,
        'pcr_volume': pcr_volume,
        'total_call_oi': calls['oi'].sum(),
        'total_put_oi': puts['oi'].sum(),
        'total_call_volume': calls['volume'].sum(),
        'total_put_volume': puts['volume'].sum()
    }

pcr = calculate_pcr(chain_df)
print(f"PCR (OI): {pcr['pcr_oi']:.2f}")
print(f"PCR (Volume): {pcr['pcr_volume']:.2f}")
```

**PCR Interpretation:**
- **PCR > 1.0**: More put open interest → Bullish sentiment
- **PCR < 1.0**: More call open interest → Bearish sentiment
- **PCR ≈ 1.0**: Neutral sentiment

#### Find Max Pain Strike

```python
def find_max_pain(chain_df, spot_price):
    """Find strike where option writers have minimum loss"""
    strikes = sorted(chain_df['strike'].unique())
    max_pain = None
    min_loss = float('inf')
    
    for strike in strikes:
        # Calculate total loss for option writers at this strike
        calls = chain_df[(chain_df['type'] == 'CE') & (chain_df['strike'] < strike)]
        puts = chain_df[(chain_df['type'] == 'PE') & (chain_df['strike'] > strike)]
        
        call_loss = sum((strike - c['strike']) * c['oi'] for _, c in calls.iterrows())
        put_loss = sum((p['strike'] - strike) * p['oi'] for _, p in puts.iterrows())
        
        total_loss = call_loss + put_loss
        
        if total_loss < min_loss:
            min_loss = total_loss
            max_pain = strike
    
    return max_pain

max_pain_strike = find_max_pain(chain_df, spot_price=23450.0)
print(f"Max Pain Strike: {max_pain_strike}")
```

#### IV Smile/Skew Analysis

```python
# Calculate IV for each strike
def calculate_iv_curve(chain_df, spot_price, greeks_calc):
    """Calculate IV for all strikes to visualize IV smile"""
    calls = chain_df[chain_df['type'] == 'CE'].copy()
    
    iv_data = []
    for _, row in calls.iterrows():
        if row['last_price'] > 0.5:  # Skip illiquid options
            iv = greeks_calc.implied_volatility(
                is_call=True,
                S=spot_price,
                K=row['strike'],
                T=row['expiry'],
                market_price=row['last_price']
            )
            
            moneyness = row['strike'] / spot_price  # ATM = 1.0
            
            iv_data.append({
                'strike': row['strike'],
                'moneyness': moneyness,
                'iv': iv * 100,  # Convert to percentage
                'last_price': row['last_price']
            })
    
    return pd.DataFrame(iv_data)

iv_curve = calculate_iv_curve(chain_df, 23450.0, greeks_calc)

# Find ATM IV
atm_iv = iv_curve[abs(iv_curve['moneyness'] - 1.0) < 0.01]['iv'].mean()
print(f"ATM IV: {atm_iv:.2f}%")

# Detect skew
otm_calls = iv_curve[iv_curve['moneyness'] > 1.05]['iv'].mean()
otm_puts = iv_curve[iv_curve['moneyness'] < 0.95]['iv'].mean()
skew = otm_puts - otm_calls

print(f"IV Skew: {skew:.2f}% (Put IV - Call IV)")
```

---

## Part 4: Market Breadth Analytics

### MarketBreadthAnalytics Class

**File:** `src/analytics/market_breadth.py`

Analyzes market breadth using advancers, decliners, and unchanged counts.

#### Basic Usage

```python
from src.analytics.market_breadth import MarketBreadthAnalytics

# Initialize
breadth = MarketBreadthAnalytics()

# Analyze breadth data
breadth_data = {
    "advancers": 120,
    "decliners": 80,
    "unchanged": 10
}

result = breadth.analyze(breadth_data)

print(f"Breadth Score: {result['breadth_score']:.4f}")
print(f"Advance Ratio: {result['adv_ratio']:.2%}")
print(f"Decline Ratio: {result['dec_ratio']:.2%}")
```

**Output:**
```
Breadth Score: 0.1905  (Bullish)
Advance Ratio: 57.14%
Decline Ratio: 38.10%
```

#### Breadth Interpretation

```python
def interpret_breadth(breadth_score):
    """Interpret market breadth score"""
    if breadth_score > 0.3:
        return "Strong Bullish"
    elif breadth_score > 0.1:
        return "Moderately Bullish"
    elif breadth_score > -0.1:
        return "Neutral"
    elif breadth_score > -0.3:
        return "Moderately Bearish"
    else:
        return "Strong Bearish"

interpretation = interpret_breadth(result['breadth_score'])
print(f"Market Breadth: {interpretation}")
```

#### Options Breadth

Calculate breadth specifically for options:

```python
def calculate_options_breadth(chain_df, spot_price):
    """Calculate breadth metrics for option chain"""
    calls = chain_df[chain_df['type'] == 'CE']
    puts = chain_df[chain_df['type'] == 'PE']
    
    # ITM/OTM classification
    itm_calls = len(calls[calls['strike'] < spot_price])
    otm_calls = len(calls[calls['strike'] >= spot_price])
    itm_puts = len(puts[puts['strike'] > spot_price])
    otm_puts = len(puts[puts['strike'] <= spot_price])
    
    # Volume-weighted breadth
    call_volume = calls['volume'].sum()
    put_volume = puts['volume'].sum()
    total_volume = call_volume + put_volume
    
    return {
        "itm_calls": itm_calls,
        "otm_calls": otm_calls,
        "itm_puts": itm_puts,
        "otm_puts": otm_puts,
        "call_volume_pct": call_volume / total_volume * 100 if total_volume > 0 else 0,
        "put_volume_pct": put_volume / total_volume * 100 if total_volume > 0 else 0
    }

options_breadth = calculate_options_breadth(chain_df, 23450.0)
print(f"ITM Calls: {options_breadth['itm_calls']}")
print(f"OTM Calls: {options_breadth['otm_calls']}")
print(f"Call Volume: {options_breadth['call_volume_pct']:.1f}%")
```

---

## Part 5: Complete Workflow Examples

### Example 1: Full Option Analysis Pipeline

```python
#!/usr/bin/env python3
"""
Complete option analysis for a single index
"""

from datetime import date
from src.broker.kite_provider import KiteProvider
from src.analytics.option_greeks import OptionGreeks
from src.analytics.option_chain import OptionChainAnalytics

# Initialize
provider = KiteProvider()
greeks_calc = OptionGreeks(risk_free_rate=0.05)
chain_analytics = OptionChainAnalytics(provider)

# Fetch spot price
spot_data = provider.get_spot_quote("NIFTY")
spot_price = spot_data['last_price']
print(f"NIFTY Spot: {spot_price}")

# Fetch option chain
expiry = date(2025, 11, 28)
chain_df = chain_analytics.fetch_option_chain(
    index_symbol="NIFTY",
    expiry_date=expiry,
    strike_range=(spot_price - 500, spot_price + 500)
)

# Calculate ATM IV
atm_strike = round(spot_price / 50) * 50  # Round to nearest 50
atm_call = chain_df[
    (chain_df['type'] == 'CE') & 
    (chain_df['strike'] == atm_strike)
].iloc[0]

atm_iv = greeks_calc.implied_volatility(
    is_call=True,
    S=spot_price,
    K=atm_strike,
    T=expiry,
    market_price=atm_call['last_price']
)

print(f"ATM Strike: {atm_strike}")
print(f"ATM Call Premium: ₹{atm_call['last_price']:.2f}")
print(f"ATM IV: {atm_iv*100:.2f}%")

# Calculate Greeks for ATM call
greeks = greeks_calc.black_scholes(
    is_call=True,
    S=spot_price,
    K=atm_strike,
    T=expiry,
    sigma=atm_iv
)

print(f"\nATM Call Greeks:")
print(f"  Delta: {greeks['delta']:.4f}")
print(f"  Gamma: {greeks['gamma']:.6f}")
print(f"  Theta: ₹{greeks['theta']:.2f}/day")
print(f"  Vega: ₹{greeks['vega']:.2f}/1% IV")

# Calculate PCR
calls = chain_df[chain_df['type'] == 'CE']
puts = chain_df[chain_df['type'] == 'PE']
pcr_oi = puts['oi'].sum() / calls['oi'].sum()

print(f"\nPut-Call Ratio (OI): {pcr_oi:.2f}")
print(f"Total Call OI: {calls['oi'].sum():,}")
print(f"Total Put OI: {puts['oi'].sum():,}")
```

### Example 2: IV Smile Visualization

```python
#!/usr/bin/env python3
"""
Calculate and display IV smile curve
"""

import matplotlib.pyplot as plt
from datetime import date

# ... (initialize providers as above)

# Calculate IV for range of strikes
strikes = range(23000, 24000, 50)
call_ivs = []
put_ivs = []

for strike in strikes:
    # Call IV
    call_data = chain_df[
        (chain_df['type'] == 'CE') & 
        (chain_df['strike'] == strike)
    ]
    
    if not call_data.empty and call_data.iloc[0]['last_price'] > 0.5:
        iv = greeks_calc.implied_volatility(
            is_call=True,
            S=spot_price,
            K=strike,
            T=expiry,
            market_price=call_data.iloc[0]['last_price']
        )
        call_ivs.append((strike, iv * 100))
    
    # Put IV
    put_data = chain_df[
        (chain_df['type'] == 'PE') & 
        (chain_df['strike'] == strike)
    ]
    
    if not put_data.empty and put_data.iloc[0]['last_price'] > 0.5:
        iv = greeks_calc.implied_volatility(
            is_call=False,
            S=spot_price,
            K=strike,
            T=expiry,
            market_price=put_data.iloc[0]['last_price']
        )
        put_ivs.append((strike, iv * 100))

# Plot IV smile
if call_ivs and put_ivs:
    call_strikes, call_iv_values = zip(*call_ivs)
    put_strikes, put_iv_values = zip(*put_ivs)
    
    plt.figure(figsize=(12, 6))
    plt.plot(call_strikes, call_iv_values, 'g-', label='Call IV', linewidth=2)
    plt.plot(put_strikes, put_iv_values, 'r-', label='Put IV', linewidth=2)
    plt.axvline(spot_price, color='blue', linestyle='--', label=f'Spot: {spot_price:.0f}')
    plt.xlabel('Strike Price')
    plt.ylabel('Implied Volatility (%)')
    plt.title(f'NIFTY IV Smile - Expiry: {expiry}')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig('iv_smile.png', dpi=300, bbox_inches='tight')
    print("IV smile chart saved to iv_smile.png")
```

### Example 3: Greeks Heatmap

```python
#!/usr/bin/env python3
"""
Generate Greeks heatmap for option chain
"""

import pandas as pd
import numpy as np

# Calculate Greeks for all strikes
greeks_data = []

for _, row in chain_df.iterrows():
    if row['last_price'] > 0.5:  # Skip illiquid
        # Calculate IV
        iv = greeks_calc.implied_volatility(
            is_call=(row['type'] == 'CE'),
            S=spot_price,
            K=row['strike'],
            T=expiry,
            market_price=row['last_price']
        )
        
        # Calculate Greeks
        greeks = greeks_calc.black_scholes(
            is_call=(row['type'] == 'CE'),
            S=spot_price,
            K=row['strike'],
            T=expiry,
            sigma=iv
        )
        
        greeks_data.append({
            'strike': row['strike'],
            'type': row['type'],
            'iv': iv * 100,
            'delta': greeks['delta'],
            'gamma': greeks['gamma'],
            'theta': greeks['theta'],
            'vega': greeks['vega']
        })

greeks_df = pd.DataFrame(greeks_data)

# Display heatmap data
print("\nGreeks Summary:")
print(greeks_df.groupby('type').agg({
    'delta': ['mean', 'min', 'max'],
    'gamma': ['mean', 'max'],
    'theta': ['mean', 'min'],
    'vega': ['mean', 'max']
}))
```

---

## Part 6: Configuration Reference

### Greeks Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `G6_RISK_FREE_RATE` | 0.05 | Annual risk-free rate (5%) |
| `G6_ENABLE_GREEKS` | 1 | Enable Greeks calculation |
| `G6_ENABLE_IV_CALCULATION` | 1 | Enable IV solver |
| `G6_IV_MAX_ITERATIONS` | 100 | Max IV solver iterations |
| `G6_IV_PRECISION` | 0.00001 | IV convergence threshold |
| `G6_IV_MIN` | 0.01 | Minimum IV (1%) |
| `G6_IV_MAX` | 5.0 | Maximum IV (500%) |

### Analytics Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `G6_ENABLE_ANALYTICS` | 1 | Enable analytics module |
| `G6_ANALYTICS_TIMEOUT` | 10.0 | Analytics timeout (seconds) |
| `G6_PCR_ENABLED` | 1 | Calculate PCR |
| `G6_BREADTH_ENABLED` | 1 | Calculate breadth |
| `G6_VOL_SURFACE_ENABLED` | 0 | Volatility surface (experimental) |

### Performance Tuning

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `G6_ANALYTICS_PARALLEL` | 0 | Parallel IV calculation |
| `G6_ANALYTICS_CACHE_SIZE` | 1000 | Greeks cache size |
| `G6_ANALYTICS_CACHE_TTL` | 60 | Cache TTL (seconds) |

---

## Part 7: Monitoring & Troubleshooting

### Analytics Metrics

**Prometheus metrics at `http://localhost:9108/metrics`:**

```promql
# IV solver performance
histogram_quantile(0.95, g6_iv_solver_iterations_bucket)
rate(g6_iv_solver_failures_total[5m])

# Greeks calculation time
histogram_quantile(0.95, g6_greeks_calculation_duration_seconds_bucket)

# Analytics throughput
rate(g6_analytics_calculations_total[1m])

# PCR tracking
g6_pcr_oi{index="NIFTY"}
g6_pcr_volume{index="NIFTY"}
```

### Common Issues

#### Issue 1: "IV solver not converging"

**Cause:** Market price incompatible with BS model  
**Solution:**

```python
# Increase max iterations
iv = greeks_calc.implied_volatility(
    ...,
    max_iterations=200,  # Instead of 100
    min_iv=0.001,        # Lower minimum
    max_iv=10.0          # Higher maximum
)

# Check if option is expired
if T <= 0:
    print("Option expired, IV not meaningful")
```

#### Issue 2: "Negative option prices"

**Cause:** Invalid parameters or expired options  
**Solution:**

```python
# Validate inputs
assert S > 0, "Spot must be positive"
assert K > 0, "Strike must be positive"
assert T >= 0, "Time to expiry cannot be negative"
assert sigma > 0, "Volatility must be positive"

# Check for expiry
dte_years = OptionGreeks._calculate_dte(expiry_date)
if dte_years <= 0:
    print("Option has expired")
```

#### Issue 3: "Greeks calculation slow"

**Cause:** Too many strikes or inefficient loops  
**Solution:**

```python
# Enable caching
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_greeks(is_call, S, K, T, sigma):
    return greeks_calc.black_scholes(is_call, S, K, T, sigma=sigma)

# Vectorize calculations (use pandas)
import numpy as np

# Batch calculate for all strikes
strikes = chain_df['strike'].unique()
greeks_list = [
    greeks_calc.black_scholes(True, spot, k, T, sigma=0.15)
    for k in strikes
]
```

#### Issue 4: "PCR values extreme"

**Cause:** Low liquidity or data errors  
**Solution:**

```python
# Filter illiquid options
liquid_chain = chain_df[
    (chain_df['volume'] > 100) &
    (chain_df['oi'] > 1000) &
    (chain_df['last_price'] > 0.5)
]

# Clamp PCR to reasonable range
pcr = calculate_pcr(liquid_chain)['pcr_oi']
pcr = max(0.1, min(10.0, pcr))  # Clamp between 0.1 and 10.0
```

### Debug Mode

```python
# Enable analytics debug logging
import logging
logging.getLogger('src.analytics').setLevel(logging.DEBUG)

# Or via environment
G6_LOG_LEVEL_ANALYTICS=DEBUG
```

---

## Part 8: Best Practices

### ✅ DO

1. **Cache Greeks calculations:**
   ```python
   # Reuse Greeks for same parameters
   greeks_cache = {}
   key = (is_call, S, K, T, sigma)
   if key in greeks_cache:
       return greeks_cache[key]
   ```

2. **Validate inputs before calculation:**
   ```python
   if market_price <= 0 or T <= 0:
       return 0.0  # Skip invalid data
   ```

3. **Use IV with reasonable bounds:**
   ```python
   iv = greeks_calc.implied_volatility(
       ...,
       min_iv=0.05,   # 5% minimum
       max_iv=2.0     # 200% maximum
   )
   ```

4. **Monitor solver performance:**
   ```python
   iv, iterations = greeks_calc.implied_volatility(
       ...,
       return_iterations=True
   )
   if iterations > 50:
       logger.warning(f"Slow convergence: {iterations} iterations")
   ```

5. **Filter illiquid options:**
   ```python
   # Only calculate IV for liquid options
   if option['volume'] > 100 and option['last_price'] > 1.0:
       iv = greeks_calc.implied_volatility(...)
   ```

### ❌ DON'T

1. **Don't calculate IV for expired options** - Returns 0 or min_iv
2. **Don't use IV for deep ITM options** - Unreliable due to low time value
3. **Don't ignore solver convergence** - Check iteration count
4. **Don't recalculate Greeks unnecessarily** - Use caching
5. **Don't use PCR without filtering** - Illiquid options skew ratios

---

## Part 9: Integration Examples

### Integration with Collectors

```python
# In collection pipeline
from src.analytics.option_greeks import OptionGreeks

greeks_calc = OptionGreeks()

# Calculate Greeks during collection
for option in options_data:
    if config.get('enable_greeks'):
        greeks = greeks_calc.black_scholes(
            is_call=(option['type'] == 'CE'),
            S=spot_price,
            K=option['strike'],
            T=option['expiry'],
            market_price=option['last_price'],
            sigma=0.15  # Use ATM IV or historical vol
        )
        
        option['delta'] = greeks['delta']
        option['gamma'] = greeks['gamma']
        option['theta'] = greeks['theta']
        option['vega'] = greeks['vega']
```

### Integration with Storage

```python
# Save analytics to CSV
analytics_df = pd.DataFrame(greeks_data)
analytics_df.to_csv(
    f'data/analytics/NIFTY_{date.today()}_greeks.csv',
    index=False
)

# Save to InfluxDB
from src.storage.influx_sink import InfluxSink

influx = InfluxSink()
for _, row in analytics_df.iterrows():
    influx.write_point(
        measurement="option_greeks",
        tags={"index": "NIFTY", "strike": row['strike']},
        fields={
            "iv": row['iv'],
            "delta": row['delta'],
            "gamma": row['gamma']
        }
    )
```

---

## Summary

The **Analytics System** provides:

✅ **Black-Scholes Pricing** - Theoretical option prices  
✅ **Option Greeks** - Delta, Gamma, Theta, Vega, Rho  
✅ **IV Solver** - Newton-Raphson implied volatility  
✅ **Option Chain Analytics** - PCR, breadth, max pain  
✅ **Market Breadth** - Advancers/decliners analysis  
✅ **Caching & Performance** - Optimized calculations  

**Quick Start:**

```python
from src.analytics.option_greeks import OptionGreeks

greeks_calc = OptionGreeks(risk_free_rate=0.05)

# Calculate Greeks
greeks = greeks_calc.black_scholes(
    is_call=True, S=23450, K=23500, T=0.082, sigma=0.15
)

# Calculate IV
iv = greeks_calc.implied_volatility(
    is_call=True, S=23450, K=23500, T=0.082, market_price=112.5
)
```

**Next Steps:**
1. Review `docs/STORAGE_GUIDE.md` for persisting analytics
2. Review `docs/METRICS_GUIDE.md` for monitoring
3. Review `docs/PANELS_GUIDE.md` for displaying results

---

*For mathematical details, see Black-Scholes literature and options theory texts.*
