import os
from src.config.env_loader import ensure_loaded

# Clear a couple of flags to ensure they come from file
for k in ("ENABLE_PATH_FORECAST_PROM_METRICS", "PATH_FORECAST_META_METRICS", "GF_SERVER_HTTP_PORT"):
    os.environ.pop(k, None)

ensure_loaded()
print("ENABLE_PATH_FORECAST_PROM_METRICS:", os.environ.get("ENABLE_PATH_FORECAST_PROM_METRICS"))
print("PATH_FORECAST_META_METRICS:", os.environ.get("PATH_FORECAST_META_METRICS"))
print("GF_SERVER_HTTP_PORT:", os.environ.get("GF_SERVER_HTTP_PORT"))
