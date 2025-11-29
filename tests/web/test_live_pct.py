
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pathlib import Path

from src.web.dashboard.app import app

@pytest.fixture
def client():
    return TestClient(app)

@patch("src.web.dashboard.routes.live._find_live_csv")
@patch("src.web.dashboard.routes.live._load_csv_rows_full")
def test_live_csv_pct_calculation(mock_load, mock_find, client):
    # Setup mock data
    mock_find.return_value = Path("dummy.csv")
    
    # Create 3 rows of data
    # Row 1: Base values
    # Row 2: +10%
    # Row 3: -50%
    mock_data = [
        {"time": 1000, "ts": 1000, "tp": 100, "index_price": 100.0, "ce_vol": 1000},
        {"time": 2000, "ts": 2000, "tp": 110, "index_price": 110.0, "ce_vol": 1100},
        {"time": 3000, "ts": 3000, "tp": 50, "index_price": 50.0, "ce_vol": 500},
    ]
    mock_load.return_value = mock_data

    # Request with pct=1
    response = client.get(
        "/api/live_csv", 
        params={
            "index": "NIFTY", 
            "pct": "1", 
            "pct_fields": "index_price,ce_vol"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert len(data) == 3
    
    # Check Row 1 (Base) - Should be 0.0 or None depending on implementation, 
    # but usually (val/base - 1)*100. 100/100 - 1 = 0.
    assert data[0]["index_price_pct"] == 0.0
    assert data[0]["ce_vol_pct"] == 0.0
    
    # Check Row 2 (+10%)
    # (110/100 - 1) * 100 = 10.0
    assert data[1]["index_price_pct"] == 10.0
    assert data[1]["ce_vol_pct"] == 10.0
    
    # Check Row 3 (-50%)
    # (50/100 - 1) * 100 = -50.0
    assert data[2]["index_price_pct"] == -50.0
    assert data[2]["ce_vol_pct"] == -50.0

@patch("src.web.dashboard.routes.live._find_live_csv")
@patch("src.web.dashboard.routes.live._load_csv_rows_full")
def test_live_csv_pct_missing_base(mock_load, mock_find, client):
    # Setup mock data where first row has missing/invalid data
    mock_find.return_value = Path("dummy.csv")
    
    mock_data = [
        {"time": 1000, "ts": 1000, "tp": 100, "index_price": None}, # Invalid base
        {"time": 2000, "ts": 2000, "tp": 110, "index_price": 100.0}, # New base
        {"time": 3000, "ts": 3000, "tp": 120, "index_price": 110.0}, # +10% from new base
    ]
    mock_load.return_value = mock_data

    response = client.get(
        "/api/live_csv", 
        params={
            "index": "NIFTY", 
            "pct": "1", 
            "pct_fields": "index_price"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Row 1 should be None because no base established yet (and it is invalid itself)
    assert data[0]["index_price_pct"] is None
    
    # Row 2 establishes base 100.0. (100/100 - 1) = 0
    assert data[1]["index_price_pct"] == 0.0
    
    # Row 3: (110/100 - 1) * 100 = 10.0
    assert data[2]["index_price_pct"] == 10.0
