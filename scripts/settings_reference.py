"""Settings Summary Reference - Active Settings Only"""

print("=" * 80)
print("SETTINGS SUMMARY - Active Settings Reference")
print("=" * 80)
print()

settings = [
    {
        "name": "domain_models",
        "modes": "0=off, 1=on",
        "description": "Enable experimental domain model enrichment",
        "default": "0 (off)"
    },
    {
        "name": "trace_collector",
        "modes": "0=off, 1=on",
        "description": "Enable detailed collection tracing for debugging",
        "default": "0 (off)"
    },
    {
        "name": "quiet_mode",
        "modes": "0=normal, 1=quiet",
        "description": "Suppress non-critical logging output",
        "default": "0 (normal)"
    },
    {
        "name": "quiet_allow_trace",
        "modes": "0=off, 1=on",
        "description": "Allow trace logs even when quiet_mode=1",
        "default": "0 (off)"
    },
    {
        "name": "outage_threshold",
        "modes": "N cycles",
        "description": "Declare provider outage after N consecutive empty cycles",
        "default": "3"
    },
    {
        "name": "outage_log_every",
        "modes": "N cycles",
        "description": "Log outage warning every N cycles (prevents spam)",
        "default": "5"
    },
    {
        "name": "retry_on_empty",
        "modes": "0=off, 1=on",
        "description": "Retry API calls that return empty results",
        "default": "1 (on)"
    },
    {
        "name": "overrides_count",
        "modes": "N (read-only)",
        "description": "Number of active log level overrides",
        "default": "varies"
    }
]

for s in settings:
    print(f"{s['name']:22} : {s['modes']}")
    print(f"{'':22}   {s['description']}")
    print(f"{'':22}   Default: {s['default']}")
    print()

print("=" * 80)
print("Usage Examples:")
print("=" * 80)
print()
print("Enable debug tracing:")
print("  export G6_TRACE_COLLECTOR=1")
print()
print("Enable quiet mode with trace:")
print("  export G6_QUIET_MODE=1")
print("  export G6_QUIET_ALLOW_TRACE=1")
print()
print("Adjust outage detection:")
print("  export G6_PROVIDER_OUTAGE_THRESHOLD=5")
print("  export G6_OUTAGE_LOG_EVERY=10")
print()
