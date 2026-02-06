"""Primary providers framework namespace for G6.

Keep this file minimal to avoid importing provider implementations at
package import time. Submodules (e.g., adapters, factory, rate_limiter)
should be imported directly by consumers, e.g.:

	from src.providers.adapters.async_mock_adapter import AsyncMockProvider

This avoids hard dependencies on optional providers.

Note: A legacy facade-style package also exists at `src.provider`.
"""

__all__: list[str] = []
