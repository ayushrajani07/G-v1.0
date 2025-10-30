"""Tests for health.models module."""
from __future__ import annotations

import pytest

from src.health.models import (
    HealthLevel,
    HealthState,
    ComponentHealth,
    CheckHealth,
    HealthResponse,
    level_from_state,
)


class TestHealthLevel:
    """Test HealthLevel IntEnum."""

    def test_health_level_values(self):
        """Test HealthLevel enum values and ordering."""
        assert HealthLevel.HEALTHY == 0
        assert HealthLevel.DEGRADED == 1
        assert HealthLevel.WARNING == 2
        assert HealthLevel.CRITICAL == 3
        assert HealthLevel.UNKNOWN == 4

    def test_health_level_ordering(self):
        """Test HealthLevel ordering for comparisons."""
        assert HealthLevel.HEALTHY < HealthLevel.DEGRADED
        assert HealthLevel.DEGRADED < HealthLevel.WARNING
        assert HealthLevel.WARNING < HealthLevel.CRITICAL
        assert HealthLevel.CRITICAL < HealthLevel.UNKNOWN

    def test_health_level_iteration(self):
        """Test HealthLevel can be iterated."""
        levels = list(HealthLevel)
        assert len(levels) == 5
        assert HealthLevel.HEALTHY in levels


class TestHealthState:
    """Test HealthState string enum."""

    def test_health_state_values(self):
        """Test HealthState enum values."""
        assert HealthState.HEALTHY == "healthy"
        assert HealthState.DEGRADED == "degraded"
        assert HealthState.WARNING == "warning"
        assert HealthState.CRITICAL == "critical"
        assert HealthState.UNKNOWN == "unknown"

    def test_health_state_comparison(self):
        """Test HealthState string comparison."""
        assert HealthState.HEALTHY.value == "healthy"
        assert HealthState.CRITICAL.value == "critical"

    def test_health_state_iteration(self):
        """Test HealthState can be iterated."""
        states = list(HealthState)
        assert len(states) == 5
        assert HealthState.HEALTHY in states


class TestLevelFromState:
    """Test level_from_state mapping function."""

    def test_level_from_state_healthy(self):
        """Test mapping for healthy states."""
        assert level_from_state("healthy") == HealthLevel.HEALTHY
        assert level_from_state("ok") == HealthLevel.HEALTHY
        assert level_from_state("ready") == HealthLevel.HEALTHY
        assert level_from_state("HEALTHY") == HealthLevel.HEALTHY
        assert level_from_state("OK") == HealthLevel.HEALTHY

    def test_level_from_state_degraded(self):
        """Test mapping for degraded state."""
        assert level_from_state("degraded") == HealthLevel.DEGRADED
        assert level_from_state("DEGRADED") == HealthLevel.DEGRADED

    def test_level_from_state_warning(self):
        """Test mapping for warning states."""
        assert level_from_state("warning") == HealthLevel.WARNING
        assert level_from_state("warn") == HealthLevel.WARNING
        assert level_from_state("WARNING") == HealthLevel.WARNING

    def test_level_from_state_critical(self):
        """Test mapping for critical states."""
        assert level_from_state("critical") == HealthLevel.CRITICAL
        assert level_from_state("unhealthy") == HealthLevel.CRITICAL
        assert level_from_state("error") == HealthLevel.CRITICAL
        assert level_from_state("failed") == HealthLevel.CRITICAL
        assert level_from_state("CRITICAL") == HealthLevel.CRITICAL

    def test_level_from_state_unknown(self):
        """Test mapping for unknown/invalid states."""
        assert level_from_state("unknown") == HealthLevel.UNKNOWN
        assert level_from_state("invalid") == HealthLevel.UNKNOWN
        assert level_from_state("") == HealthLevel.UNKNOWN
        assert level_from_state("random_text") == HealthLevel.UNKNOWN

    def test_level_from_state_enum_input(self):
        """Test with HealthState enum as input."""
        assert level_from_state(HealthState.HEALTHY) == HealthLevel.HEALTHY
        assert level_from_state(HealthState.DEGRADED) == HealthLevel.DEGRADED
        assert level_from_state(HealthState.WARNING) == HealthLevel.WARNING
        assert level_from_state(HealthState.CRITICAL) == HealthLevel.CRITICAL
        assert level_from_state(HealthState.UNKNOWN) == HealthLevel.UNKNOWN

    def test_level_from_state_case_insensitive(self):
        """Test case-insensitive matching."""
        assert level_from_state("Healthy") == HealthLevel.HEALTHY
        assert level_from_state("WaRnInG") == HealthLevel.WARNING
        assert level_from_state("CRITICAL") == HealthLevel.CRITICAL

    def test_level_from_state_exception_handling(self):
        """Test graceful handling of invalid input."""
        # None or objects without proper string representation
        assert level_from_state(None) == HealthLevel.UNKNOWN  # type: ignore
        assert level_from_state(123) == HealthLevel.UNKNOWN  # type: ignore


class TestComponentHealth:
    """Test ComponentHealth dataclass."""

    def test_component_health_creation(self):
        """Test basic ComponentHealth creation."""
        component = ComponentHealth(
            name="database",
            status="healthy",
            message="Database connection active",
            last_check="2025-10-27T09:15:00Z",
        )
        
        assert component.name == "database"
        assert component.status == "healthy"
        assert component.message == "Database connection active"
        assert component.last_check == "2025-10-27T09:15:00Z"

    def test_component_health_defaults(self):
        """Test ComponentHealth default values."""
        component = ComponentHealth(name="api")
        
        assert component.name == "api"
        assert component.status == "unknown"
        assert component.message == ""
        assert component.last_check is None
        assert component.details == {}

    def test_component_health_with_details(self):
        """Test ComponentHealth with custom details."""
        component = ComponentHealth(
            name="redis",
            status="degraded",
            details={"latency_ms": 150, "connections": 45},
        )
        
        assert component.details["latency_ms"] == 150
        assert component.details["connections"] == 45

    def test_component_health_level_property(self):
        """Test level property derives from status."""
        healthy = ComponentHealth(name="svc1", status="healthy")
        degraded = ComponentHealth(name="svc2", status="degraded")
        warning = ComponentHealth(name="svc3", status="warning")
        critical = ComponentHealth(name="svc4", status="critical")
        unknown = ComponentHealth(name="svc5", status="unknown")
        
        assert healthy.level == HealthLevel.HEALTHY
        assert degraded.level == HealthLevel.DEGRADED
        assert warning.level == HealthLevel.WARNING
        assert critical.level == HealthLevel.CRITICAL
        assert unknown.level == HealthLevel.UNKNOWN

    def test_component_health_level_with_aliases(self):
        """Test level property handles status aliases."""
        ok_component = ComponentHealth(name="svc", status="ok")
        error_component = ComponentHealth(name="svc", status="error")
        
        assert ok_component.level == HealthLevel.HEALTHY
        assert error_component.level == HealthLevel.CRITICAL


class TestCheckHealth:
    """Test CheckHealth dataclass."""

    def test_check_health_creation(self):
        """Test basic CheckHealth creation."""
        check = CheckHealth(
            name="disk_space",
            status="healthy",
            message="Disk usage at 45%",
            last_check="2025-10-27T09:15:00Z",
        )
        
        assert check.name == "disk_space"
        assert check.status == "healthy"
        assert check.message == "Disk usage at 45%"
        assert check.last_check == "2025-10-27T09:15:00Z"

    def test_check_health_defaults(self):
        """Test CheckHealth default values."""
        check = CheckHealth(name="memory_check")
        
        assert check.name == "memory_check"
        assert check.status == "unknown"
        assert check.message == ""
        assert check.last_check is None
        assert check.details == {}

    def test_check_health_with_details(self):
        """Test CheckHealth with custom details."""
        check = CheckHealth(
            name="api_latency",
            status="warning",
            details={"p95_ms": 250, "p99_ms": 500, "threshold_ms": 200},
        )
        
        assert check.details["p95_ms"] == 250
        assert check.details["threshold_ms"] == 200

    def test_check_health_level_property(self):
        """Test level property derives from status."""
        healthy_check = CheckHealth(name="check1", status="healthy")
        warning_check = CheckHealth(name="check2", status="warning")
        critical_check = CheckHealth(name="check3", status="critical")
        
        assert healthy_check.level == HealthLevel.HEALTHY
        assert warning_check.level == HealthLevel.WARNING
        assert critical_check.level == HealthLevel.CRITICAL

    def test_check_health_level_with_failed_status(self):
        """Test level property handles 'failed' as critical."""
        check = CheckHealth(name="failing_check", status="failed")
        assert check.level == HealthLevel.CRITICAL


class TestHealthResponse:
    """Test HealthResponse dataclass."""

    def test_health_response_basic(self):
        """Test basic HealthResponse creation."""
        response = HealthResponse(
            timestamp="2025-10-27T09:15:00Z",
            status="healthy",
            level=HealthLevel.HEALTHY,
        )
        
        assert response.timestamp == "2025-10-27T09:15:00Z"
        assert response.status == "healthy"
        assert response.level == HealthLevel.HEALTHY
        assert response.components is None
        assert response.checks is None

    def test_health_response_with_components(self):
        """Test HealthResponse with components."""
        components = {
            "database": ComponentHealth("database", "healthy"),
            "cache": ComponentHealth("cache", "degraded"),
        }
        
        response = HealthResponse(
            timestamp="2025-10-27T09:15:00Z",
            status="degraded",
            level=HealthLevel.DEGRADED,
            components=components,
        )
        
        assert len(response.components) == 2
        assert "database" in response.components
        assert response.components["database"].status == "healthy"
        assert response.components["cache"].status == "degraded"

    def test_health_response_with_checks(self):
        """Test HealthResponse with checks."""
        checks = {
            "disk_space": CheckHealth("disk_space", "healthy"),
            "memory": CheckHealth("memory", "warning"),
        }
        
        response = HealthResponse(
            timestamp="2025-10-27T09:15:00Z",
            status="warning",
            level=HealthLevel.WARNING,
            checks=checks,
        )
        
        assert len(response.checks) == 2
        assert "disk_space" in response.checks
        assert response.checks["memory"].status == "warning"

    def test_health_response_with_components_and_checks(self):
        """Test HealthResponse with both components and checks."""
        components = {
            "api": ComponentHealth("api", "healthy"),
        }
        checks = {
            "latency": CheckHealth("latency", "warning"),
        }
        
        response = HealthResponse(
            timestamp="2025-10-27T09:15:00Z",
            status="warning",
            level=HealthLevel.WARNING,
            components=components,
            checks=checks,
        )
        
        assert response.components is not None
        assert response.checks is not None
        assert len(response.components) == 1
        assert len(response.checks) == 1

    def test_health_response_critical_level(self):
        """Test HealthResponse with critical status."""
        response = HealthResponse(
            timestamp="2025-10-27T09:15:00Z",
            status="critical",
            level=HealthLevel.CRITICAL,
            components={
                "database": ComponentHealth("database", "critical", "Connection lost"),
            },
        )
        
        assert response.level == HealthLevel.CRITICAL
        assert response.components["database"].message == "Connection lost"


class TestIntegration:
    """Integration tests across health models."""

    def test_component_to_response_workflow(self):
        """Test creating HealthResponse from components."""
        components = {
            "database": ComponentHealth("database", "healthy", "All queries < 50ms"),
            "redis": ComponentHealth("redis", "degraded", "High memory usage"),
            "queue": ComponentHealth("queue", "healthy", "0 backlog"),
        }
        
        # Determine overall status (worst component level)
        max_level = max(c.level for c in components.values())
        status_map = {
            HealthLevel.HEALTHY: "healthy",
            HealthLevel.DEGRADED: "degraded",
            HealthLevel.WARNING: "warning",
            HealthLevel.CRITICAL: "critical",
            HealthLevel.UNKNOWN: "unknown",
        }
        
        response = HealthResponse(
            timestamp="2025-10-27T09:15:00Z",
            status=status_map[max_level],
            level=max_level,
            components=components,
        )
        
        assert response.level == HealthLevel.DEGRADED  # Worst is degraded
        assert response.status == "degraded"
        assert len(response.components) == 3

    def test_check_to_response_workflow(self):
        """Test creating HealthResponse from checks."""
        checks = {
            "disk": CheckHealth("disk", "healthy", "75% free"),
            "memory": CheckHealth("memory", "warning", "85% used"),
            "cpu": CheckHealth("cpu", "healthy", "40% utilized"),
        }
        
        max_level = max(c.level for c in checks.values())
        
        response = HealthResponse(
            timestamp="2025-10-27T09:15:00Z",
            status="warning",
            level=max_level,
            checks=checks,
        )
        
        assert response.level == HealthLevel.WARNING
        assert response.checks["memory"].level == HealthLevel.WARNING

    def test_level_comparison_workflow(self):
        """Test comparing health levels for prioritization."""
        components = [
            ComponentHealth("svc1", "healthy"),
            ComponentHealth("svc2", "warning"),
            ComponentHealth("svc3", "degraded"),
        ]
        
        # Sort by severity (worst first)
        sorted_components = sorted(components, key=lambda c: c.level, reverse=True)
        
        assert sorted_components[0].status == "warning"
        assert sorted_components[1].status == "degraded"
        assert sorted_components[2].status == "healthy"

    def test_full_health_status_aggregation(self):
        """Test complete health status aggregation scenario."""
        components = {
            "database": ComponentHealth("database", "healthy"),
            "api": ComponentHealth("api", "degraded"),
        }
        
        checks = {
            "disk": CheckHealth("disk", "healthy"),
            "memory": CheckHealth("memory", "warning"),
        }
        
        # Aggregate all levels
        all_levels = [c.level for c in components.values()] + [c.level for c in checks.values()]
        max_level = max(all_levels)
        
        response = HealthResponse(
            timestamp="2025-10-27T10:00:00Z",
            status="warning",
            level=max_level,
            components=components,
            checks=checks,
        )
        
        assert response.level == HealthLevel.WARNING
        assert len(response.components) == 2
        assert len(response.checks) == 2
