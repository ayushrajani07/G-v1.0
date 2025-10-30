#!/usr/bin/env python3
"""
Direct data collection script for G6 Platform.
Bypasses the main loop to force immediate data collection.
"""

import datetime
import logging
import os
import sys
from typing import Any

from src.config.env_config import EnvConfig

# Module imports (moved from late imports)
from src.broker.kite_provider import kite_provider_factory
from src.storage.csv_sink import CsvSink
from src.error_handling import handle_provider_error, handle_data_collection_error, handle_collector_error

try:  # Optional dependency
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # pragma: no cover - optional path
    def load_dotenv(*_a, **_k):  # type: ignore
        print("[direct_collect] Warning: python-dotenv not installed; proceeding with system environment only")
from src.utils.logging_utils import setup_logging
from src.utils.path_utils import data_subdir, ensure_sys_path

# Ensure sys.path only once (idempotent)
ensure_sys_path()

setup_logging(level="DEBUG", log_file="logs/direct_collect.log")
logger = logging.getLogger("g6.direct_collect")


def normalize_instrument(instrument: Any) -> dict[str, Any] | None:
    """Return a plain dict representation of an instrument entry.

    Supports:
    - Native dict objects (copied)
    - Objects with __dict__
    - Namedtuples / dataclasses via _asdict()
    - Generic attribute containers (whitelist of expected fields)
    """
    if instrument is None:
        return None

    if isinstance(instrument, dict):
        # Copy to avoid accidental upstream mutation
        return instrument.copy()

    # namedtuple / dataclass like
    if hasattr(instrument, "_asdict"):
        try:
            return dict(instrument._asdict())  # type: ignore
        except Exception:
            pass

    # Generic object with __dict__
    if hasattr(instrument, "__dict__") and isinstance(instrument.__dict__, dict):
        # Shallow copy
        return dict(instrument.__dict__)

    # Last resort: pick known attributes
    candidate_fields = [
        "instrument_token", "exchange_token", "tradingsymbol", "name", "last_price",
        "expiry", "strike", "tick_size", "lot_size", "instrument_type", "segment", "exchange"
    ]
    extracted = {}
    for f in candidate_fields:
        if hasattr(instrument, f):
            extracted[f] = getattr(instrument, f)
    if extracted:
        return extracted
    return None

def main():
    """Direct data collection entry point."""
    # Load environment variables
    load_dotenv()
    logger.info("===== G6 DIRECT DATA COLLECTOR =====")
    logger.info("Environment variables loaded from .env file")

    # Required modules already imported at module top

    # Initialize Kite provider directly
    try:
        logger.info("Initializing Kite provider...")
        api_key = EnvConfig.get_str("KITE_API_KEY", "")
        access_token = EnvConfig.get_str("KITE_ACCESS_TOKEN", "")

        if not api_key or not access_token:
            logger.error("KITE_API_KEY or KITE_ACCESS_TOKEN not set in environment")
            return 1

        kite_provider = kite_provider_factory(api_key=api_key, access_token=access_token)
        logger.info("Kite provider initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize Kite provider: %s", e, exc_info=True)
        try:
            handle_provider_error(e, component="direct_collect.init_kite", context={"phase": "init"})
        except Exception:
            pass
        return 1

    # Initialize CSV sink
    csv_dir = data_subdir('g6_direct_data')
    csv_sink = CsvSink(base_dir=csv_dir)
    logger.info("CSV sink initialized with base_dir: %s", csv_sink.base_dir)

    # Get current timestamp
    now = datetime.datetime.now()  # local-ok
    logger.info("Current timestamp: %s", now)

    # Collect NIFTY data
    try:
        index_symbol = "NIFTY"
        logger.info("Collecting data for %s...", index_symbol)

        # Get current index price
        instruments = [("NSE", "NIFTY 50")]
        ltp_data = kite_provider.get_ltp(instruments)
        logger.info("LTP data: %s", ltp_data)

        # Extract LTP and calculate ATM strike
        ltp = 0
        if isinstance(ltp_data, dict):
            for key, data in ltp_data.items():
                ltp = data.get('last_price', 0)
        else:
            logger.error("LTP data is not a dict: %s", type(ltp_data))

        # Round to nearest 50
        atm_strike = round(ltp / 50) * 50
        logger.info("%s current price: %s, ATM strike: %s", index_symbol, ltp, atm_strike)

        # Calculate strikes to collect
        strikes = []
        for i in range(1, 6):  # 5 strikes on each side
            strikes.append(atm_strike - (i * 50))  # ITM strikes

        strikes.append(atm_strike)  # ATM strike

        for i in range(1, 6):
            strikes.append(atm_strike + (i * 50))  # OTM strikes

        strikes.sort()
        logger.info("Collecting data for strikes: %s", strikes)

        # Get this week's expiry
        expiry_dates = kite_provider.get_expiry_dates(index_symbol)
        logger.info("Available expiry dates: %s", expiry_dates)

        # Use first expiry if available
        if expiry_dates:
            expiry_date = expiry_dates[0]
            logger.info("Using expiry date: %s", expiry_date)

            # Get option instruments
            raw_instruments = kite_provider.option_instruments(index_symbol, expiry_date, strikes)
            logger.info("Found %s option instruments (raw)", len(raw_instruments))

            if raw_instruments:
                logger.debug("Sample raw instrument: %s", raw_instruments[0])

                options_data: dict[str, dict[str, Any]] = {}
                skipped = 0
                for inst in raw_instruments:
                    norm = normalize_instrument(inst)
                    if not norm:
                        skipped += 1
                        continue
                    symbol = norm.get("tradingsymbol") or norm.get("symbol")
                    if not symbol:
                        skipped += 1
                        continue
                    # Ensure symbol uniqueness (last one wins, but log duplicates)
                    if symbol in options_data:
                        logger.debug("Duplicate symbol encountered, overwriting: %s", symbol)
                    options_data[symbol] = norm

                logger.info("Normalized instruments: kept %s, skipped %s", len(options_data), skipped)

                if options_data:
                    quote_instruments = [("NFO", sym) for sym in options_data.keys()]
                    logger.info("Requesting quotes for %s instruments", len(quote_instruments))
                    quotes = kite_provider.get_quote(quote_instruments)
                    
                    if quotes:
                        logger.info("Received %s quote entries", len(quotes))

                        updated_fields = 0
                        for exch, sym in quote_instruments:
                            q_key = f"{exch}:{sym}"
                            quote_payload_any = quotes.get(q_key)
                            if not isinstance(quote_payload_any, dict):
                                continue
                            quote_payload = quote_payload_any  # Already validated as dict
                            sym_entry_any = options_data.get(sym, {})
                            if not isinstance(sym_entry_any, dict):
                                continue
                            sym_entry: dict[str, Any] = sym_entry_any  # explicit type
                            for field in ("last_price", "volume", "oi", "depth"):
                                if field in quote_payload:
                                    sym_entry[field] = quote_payload[field]  # type: ignore[literal-required]
                                    updated_fields += 1
                            options_data[sym] = sym_entry
                        logger.info("Updated option entries with %s quote fields", updated_fields)

                        # Persist
                        logger.info("Writing %s normalized option records to CSV", len(options_data))
                        csv_sink.write_options_data(index_symbol, expiry_date, options_data, now)

                        # Post-write verification
                        expected_dir = f"{csv_sink.base_dir}/{index_symbol}/{expiry_date}"
                        expected_file = f"{expected_dir}/{now.strftime('%Y-%m-%d')}.csv"
                        logger.info("Verifying data file presence at %s", expected_file)
                        if os.path.exists(expected_file):
                            try:
                                file_size = os.path.getsize(expected_file)
                                logger.info("Data file OK (size=%s bytes)", file_size)
                                with open(expected_file) as fh:
                                    preview = fh.readlines()[:5]
                                logger.debug("File preview (first 5 lines): %s", preview)
                            except Exception as read_err:
                                logger.error("Error reading written CSV: %s", read_err)
                                try:
                                    handle_data_collection_error(read_err, component="direct_collect.verify_csv", data_type="csv_read", context={"file": expected_file})
                                except Exception:
                                    pass
                        else:
                            logger.warning("Expected CSV file not found after write attempt")
                            if not os.path.exists(expected_dir):
                                logger.warning("Target directory missing; attempting creation + sentinel file")
                                try:
                                    os.makedirs(expected_dir, exist_ok=True)
                                    sentinel = os.path.join(expected_dir, "_write_check.txt")
                                    with open(sentinel, "w") as fh:
                                        fh.write("write test")
                                    logger.info("Sentinel file created to confirm permissions")
                                except Exception as dir_err:
                                    logger.error("Failed creating directory or sentinel: %s", dir_err, exc_info=True)
                                    try:
                                        handle_data_collection_error(dir_err, component="direct_collect.ensure_dir", data_type="filesystem", context={"path": expected_dir})
                                    except Exception:
                                        pass
                    else:
                        logger.warning("No quotes received from provider")
                else:
                    logger.warning("No normalized option data to write (all instruments skipped?)")

            else:
                logger.warning("No instruments found for %s with expiry %s", index_symbol, expiry_date)
        else:
            logger.warning("No expiry dates found for %s", index_symbol)

    except Exception as e:
        logger.error("Error collecting data: %s", e, exc_info=True)
        try:
            handle_collector_error(e, component="direct_collect.run", context={"stage": "collect"})
        except Exception:
            pass

    logger.info("===== DIRECT COLLECTION COMPLETED =====")
    return 0

if __name__ == "__main__":
    sys.exit(main())
