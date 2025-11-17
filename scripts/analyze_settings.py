"""Analysis of SETTINGS SUMMARY configuration flags."""

print("=" * 80)
print("SETTINGS SUMMARY - Status Analysis")
print("=" * 80)
print()

settings_analysis = [
    {
        "name": "min_volume",
        "value": "0",
        "env": "G6_FILTER_MIN_VOLUME",
        "status": "🟡 RARELY USED",
        "usage": "Filters options by minimum trading volume",
        "recommendation": "Keep - useful for filtering illiquid options",
        "notes": "Default 0 means no filtering. Could be useful to set to filter out options with no trading activity"
    },
    {
        "name": "min_oi",
        "value": "0",
        "env": "G6_FILTER_MIN_OI",
        "status": "🟡 RARELY USED",
        "usage": "Filters options by minimum open interest",
        "recommendation": "Keep - useful for filtering illiquid options",
        "notes": "Default 0 means no filtering. Useful to focus on liquid contracts"
    },
    {
        "name": "volume_percentile",
        "value": "0.0",
        "env": "G6_FILTER_VOLUME_PERCENTILE",
        "status": "🟡 RARELY USED",
        "usage": "Percentile-based volume filtering",
        "recommendation": "Keep - advanced filtering option",
        "notes": "0.0 means disabled. Could filter options below Nth percentile"
    },
    {
        "name": "salvage_enabled",
        "value": "0",
        "env": "G6_FOREIGN_EXPIRY_SALVAGE",
        "status": "🔴 OBSOLETE",
        "usage": "Legacy feature for salvaging foreign expiry data",
        "recommendation": "REMOVE - deprecated feature",
        "notes": "Related to old expiry handling logic, not used in current pipeline"
    },
    {
        "name": "foreign_expiry_salvage",
        "value": "0",
        "env": "G6_FOREIGN_EXPIRY_SALVAGE",
        "status": "🔴 OBSOLETE (DUPLICATE)",
        "usage": "Duplicate of salvage_enabled",
        "recommendation": "REMOVE - duplicate entry",
        "notes": "Same as salvage_enabled, just logged twice"
    },
    {
        "name": "recovery_strategy_legacy",
        "value": "0",
        "env": "G6_RECOVERY_STRATEGY_LEGACY",
        "status": "🔴 OBSOLETE",
        "usage": "Toggle for legacy RecoveryStrategy code path",
        "recommendation": "REMOVE - legacy fallback no longer needed",
        "notes": "Used in expiry_processor.py but only for backward compatibility"
    },
    {
        "name": "domain_models",
        "value": "0",
        "env": "G6_DOMAIN_MODELS",
        "status": "🟢 ACTIVE",
        "usage": "Enable domain model enrichment (experimental)",
        "recommendation": "Keep - future feature flag",
        "notes": "Used in CollectorSettings, controls advanced data enrichment"
    },
    {
        "name": "trace_collector",
        "value": "0",
        "env": "G6_TRACE_COLLECTOR",
        "status": "🟢 ACTIVE",
        "usage": "Enable detailed collector tracing for debugging",
        "recommendation": "Keep - debugging tool",
        "notes": "Useful for troubleshooting collection issues"
    },
    {
        "name": "quiet_mode",
        "value": "0",
        "env": "G6_QUIET_MODE",
        "status": "🟢 ACTIVE",
        "usage": "Suppress non-critical logging",
        "recommendation": "Keep - operational control",
        "notes": "Useful for reducing log noise in production"
    },
    {
        "name": "quiet_allow_trace",
        "value": "0",
        "env": "G6_QUIET_ALLOW_TRACE",
        "status": "🟢 ACTIVE",
        "usage": "Allow trace logs even in quiet mode",
        "recommendation": "Keep - debugging option",
        "notes": "Lets you trace specific issues while staying quiet"
    },
    {
        "name": "heartbeat_interval",
        "value": "0.0",
        "env": "G6_HEARTBEAT_INTERVAL",
        "status": "🟡 OPTIONAL",
        "usage": "Interval for emitting heartbeat metrics",
        "recommendation": "Keep - monitoring feature",
        "notes": "0.0 means disabled. Useful for health checks"
    },
    {
        "name": "outage_threshold",
        "value": "3",
        "env": "G6_PROVIDER_OUTAGE_THRESHOLD",
        "status": "🟢 ACTIVE",
        "usage": "Number of consecutive empty cycles before declaring provider outage",
        "recommendation": "Keep - critical for outage detection",
        "notes": "Currently used in unified_collectors.py for outage detection"
    },
    {
        "name": "outage_log_every",
        "value": "5",
        "env": "G6_OUTAGE_LOG_EVERY",
        "status": "🟢 ACTIVE",
        "usage": "Log outage warning every N cycles",
        "recommendation": "Keep - prevents log spam",
        "notes": "Avoids flooding logs during prolonged outages"
    },
    {
        "name": "retry_on_empty",
        "value": "1",
        "env": "G6_RETRY_ON_EMPTY",
        "status": "🟢 ACTIVE",
        "usage": "Retry API calls that return empty results",
        "recommendation": "Keep - reliability feature",
        "notes": "Helps recover from transient API issues"
    },
    {
        "name": "overrides_count",
        "value": "0",
        "env": "N/A",
        "status": "🟢 ACTIVE (COMPUTED)",
        "usage": "Number of active configuration overrides",
        "recommendation": "Keep - operational visibility",
        "notes": "Shows how many settings are overridden from defaults"
    },
    {
        "name": "pipeline_v2_flag",
        "value": "0",
        "env": "G6_COLLECTOR_PIPELINE_V2",
        "status": "🔴 OBSOLETE",
        "usage": "Toggle for experimental pipeline v2",
        "recommendation": "REMOVE - v2 is now default or deprecated",
        "notes": "Feature flag that should be cleaned up after migration complete"
    }
]

print()
print("SUMMARY BY STATUS:")
print("-" * 80)
print()

active = [s for s in settings_analysis if "🟢 ACTIVE" in s["status"]]
rarely_used = [s for s in settings_analysis if "🟡" in s["status"]]
obsolete = [s for s in settings_analysis if "🔴" in s["status"]]

print(f"🟢 ACTIVE & USEFUL: {len(active)}")
for s in active:
    print(f"  ✓ {s['name']:30} - {s['usage']}")

print()
print(f"🟡 RARELY USED (but keep): {len(rarely_used)}")
for s in rarely_used:
    print(f"  ? {s['name']:30} - {s['usage']}")

print()
print(f"🔴 OBSOLETE (remove): {len(obsolete)}")
for s in obsolete:
    print(f"  ✗ {s['name']:30} - {s['usage']}")

print()
print("=" * 80)
print("RECOMMENDATIONS:")
print("=" * 80)
print()
print("1. REMOVE IMMEDIATELY:")
print("   - salvage_enabled (obsolete feature)")
print("   - foreign_expiry_salvage (duplicate)")
print("   - recovery_strategy_legacy (old fallback)")
print("   - pipeline_v2_flag (feature flag cleanup)")
print()
print("2. KEEP BUT CONSIDER ENABLING:")
print("   - min_volume: Set to filter illiquid options (e.g., 100)")
print("   - min_oi: Set to filter by open interest (e.g., 50)")
print("   - quiet_mode: Enable in production to reduce log noise")
print()
print("3. KEEP AS-IS:")
print("   - outage_threshold: Working correctly (3 cycles)")
print("   - outage_log_every: Prevents log spam (every 5 cycles)")
print("   - retry_on_empty: Critical for reliability")
print("   - trace_collector: Useful debugging tool")
print("   - domain_models: Future feature")
print()
