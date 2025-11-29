import time
import pytest
from src.resilience.circuit_breaker import CircuitBreaker


def test_circuit_breaker_opens_and_recovers():
    breaker = CircuitBreaker(name='test', failure_threshold=3, recovery_timeout=0.2, half_open_max_calls=1)

    def failing():
        raise RuntimeError('fail')

    # Trip breaker
    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(failing)
    assert breaker.state == CircuitBreaker.OPEN

    # Calls while open short-circuit
    with pytest.raises(RuntimeError):
        breaker.call(lambda: 'x')

    # Wait for recovery timeout
    time.sleep(0.25)
    # Half-open trial success closes
    result = breaker.call(lambda: 'ok')
    assert result == 'ok'
    assert breaker.state == CircuitBreaker.CLOSED
