#!/usr/bin/env python3
"""
Refresh Kite API access token
Generates a fresh token using the API key and secret.

This should be run daily before market open.
"""

import logging
import os
import sys
import webbrowser

from src.config.env_config import EnvConfig

try:
    from src.error_handling import handle_api_error  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover - optional helper
    handle_api_error = None  # type: ignore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("kite-token")

def main():
    """Main function to refresh Kite token."""
    # Load environment variables via python-dotenv if available
    try:
        from dotenv import load_dotenv  # optional dependency
        try:
            load_dotenv()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Error loading .env via python-dotenv: %s", e)
    except ImportError:
        logger.debug("python-dotenv not installed; continuing without .env auto-load")

    # Check for required variables
    api_key = EnvConfig.get_str("KITE_API_KEY", "")
    api_secret = EnvConfig.get_str("KITE_API_SECRET", "")

    if not api_key:
        logger.error("KITE_API_KEY not found in environment")
        return 1

    if not api_secret:
        logger.error("KITE_API_SECRET not found in environment")
        return 1

    # Import KiteConnect; provide actionable error if missing
    try:
        from kiteconnect import KiteConnect  # optional dep
        try:  # best-effort import of TokenException for narrower handling
            from kiteconnect.exceptions import TokenException  # type: ignore
        except (ImportError, AttributeError):
            TokenException = Exception  # type: ignore[assignment]
    except ImportError as e:
        logger.error("kiteconnect package is not installed")
        if handle_api_error:
            try:
                handle_api_error(e, component="tools.refresh_kite_token", context={"op": "import_kite"})
            except Exception:
                pass
        print("\nPlease install required package:\n    pip install kiteconnect\n")
        return 1

    # Initialize Kite client
    kite = KiteConnect(api_key=api_key)

    # Get the login URL and open it in a browser
    try:
        login_url = kite.login_url()
    except Exception as e:
        logger.error("Unable to generate login URL: %s", e)
        if handle_api_error:
            try:
                handle_api_error(e, component="tools.refresh_kite_token", context={"op": "login_url"})
            except Exception:
                pass
        return 1

    logger.info("Opening login URL: %s", login_url)
    try:
        webbrowser.open(login_url)
    except (OSError, RuntimeError):
        logger.warning("Could not auto-open browser; please copy URL manually: %s", login_url)

    # Get the request token from user input
    try:
        request_token = input("Enter the request token from URL after login: ").strip()
    except OSError:
        logger.error("Stdin unavailable to read request token")
        return 1

    if not request_token:
        logger.error("Request token is required")
        return 1

    # Generate session and get access token
    try:
        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data.get("access_token") if isinstance(data, dict) else None  # type: ignore[assignment]
    except TokenException as te:  # type: ignore[misc]
        logger.error("Token exchange failed: %s", te)
        if handle_api_error:
            try:
                handle_api_error(te, component="tools.refresh_kite_token", context={"op": "exchange"})
            except Exception:
                pass
        return 1
    except Exception as e:
        logger.error("Unexpected error during token exchange: %s", e)
        if handle_api_error:
            try:
                handle_api_error(e, component="tools.refresh_kite_token", context={"op": "exchange"})
            except Exception:
                pass
        return 1

    if not access_token:
        logger.error("Failed to get access token")
        return 1

    # Update the .env file robustly
    try:
        try:
            from src.tools.token_manager import update_env_file as _update_env  # reuse if available
        except Exception:
            _update_env = None  # type: ignore[assignment]
        if callable(_update_env):
            _update_env("KITE_ACCESS_TOKEN", access_token)  # type: ignore[misc]
        else:
            env_file = ".env"
            lines: list[str] = []
            try:
                if os.path.isfile(env_file):
                    with open(env_file, encoding="utf-8") as f:
                        lines = f.read().splitlines()
            except (OSError, UnicodeDecodeError):
                lines = []
            out: list[str] = []
            found = False
            for line in lines:
                if line.startswith("KITE_ACCESS_TOKEN="):
                    out.append(f"KITE_ACCESS_TOKEN={access_token}")
                    found = True
                else:
                    out.append(line)
            if not found:
                out.append(f"KITE_ACCESS_TOKEN={access_token}")
            try:
                with open(env_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(out) + "\n")
            except OSError as e:
                logger.error("Failed to write %s: %s", env_file, e)
                return 1
        # Also refresh in-process env for immediate visibility
        try:
            os.environ["KITE_ACCESS_TOKEN"] = access_token
        except Exception:
            pass
        logger.info("Access token refreshed and saved to .env")
        return 0
    except Exception as e:
        logger.error("Error persisting token to .env: %s", e)
        if handle_api_error:
            try:
                handle_api_error(e, component="tools.refresh_kite_token", context={"op": "persist"})
            except Exception:
                pass
        return 1

if __name__ == "__main__":
    sys.exit(main())
