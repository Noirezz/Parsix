from __future__ import annotations

from decimal import Decimal

import pytest

from made_core.application.rule_engine import (
    DuplicateModuleRegistrationError,
    InMemoryRuleRegistry,
    ModuleExecutionError,
    RegistryModuleLoader,
    RuleEngineExecutor,
    UnknownModuleError,
)
from made_core.domain.enums import ResultStatus
from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent


class StubModule(DetectionModule):
    def __init__(self, module_id: str, result_id: str = "result-1", failure: Exception | None = None) -> None:
        self._module_id = module_id
        self._result_id = result_id
        self._failure = failure
        self.calls: list[EnrichedEvent] = []

    def get_module_id(self) -> str:
        return self._module_id

    def detect(self, event: EnrichedEvent) -> DetectionResult:
        self.calls.append(event)
        if self._failure is not None:
            raise self._failure
        return DetectionResult(
            result_id=self._result_id, event_id=event.event_id, module_id=self._module_id,
            timestamp=event.timestamp, asset=event.asset, metric_value=Decimal("0"),
            threshold=Decimal("1"), anomaly_ratio=Decimal("0"), status=ResultStatus.NORMAL, persistence=0,
        )


@pytest.fixture
def enriched_event(timestamp, normalized_event, market_snapshot) -> EnrichedEvent:
    from made_core.domain.models import MarketContext

    return EnrichedEvent(
        event_id=normalized_event.event_id, timestamp=timestamp, asset="BTC",
        market_context=MarketContext(asset="BTC", symbol="BTCUSDT", snapshots=(market_snapshot,)),
        normalized_data=normalized_event,
    )


@pytest.fixture
def registry() -> InMemoryRuleRegistry:
    return InMemoryRuleRegistry()


def test_registry_registers_and_retrieves_a_module(registry):
    module = StubModule("module-a")
    registry.register(module)
    assert registry.contains("module-a")
    assert registry.get("module-a") is module
    assert registry.get_active_module_ids() == ("module-a",)


def test_registry_rejects_duplicate_module_identifier(registry):
    registry.register(StubModule("module-a"))
    with pytest.raises(DuplicateModuleRegistrationError, match="module-a"):
        registry.register(StubModule("module-a"))


def test_registry_rejects_unknown_module_lookup(registry):
    with pytest.raises(UnknownModuleError, match="missing"):
        registry.get("missing")


def test_registry_preserves_multiple_independent_modules(registry):
    first, second = StubModule("module-a"), StubModule("module-b")
    registry.register(first)
    registry.register(second)
    assert registry.get_registered_modules() == (first, second)


def test_loader_resolves_registered_module(registry):
    module = StubModule("module-a")
    registry.register(module)
    assert RegistryModuleLoader(registry).load(("module-a",)) == (module,)


def test_loader_reports_unknown_module_deterministically(registry):
    with pytest.raises(UnknownModuleError, match="missing"):
        RegistryModuleLoader(registry).load(("missing",))


def test_executor_executes_one_module_once_and_preserves_event(registry, enriched_event):
    module = StubModule("module-a")
    registry.register(module)
    executor = RuleEngineExecutor(registry, RegistryModuleLoader(registry))
    result = executor.execute(enriched_event)
    assert result[0].module_id == "module-a"
    assert module.calls == [enriched_event]
    assert enriched_event.event_id == "event-1"


def test_executor_executes_multiple_modules_once_in_registration_order(registry, enriched_event):
    first, second = StubModule("module-a", "result-a"), StubModule("module-b", "result-b")
    registry.register(first)
    registry.register(second)
    results = RuleEngineExecutor(registry, RegistryModuleLoader(registry)).execute(enriched_event)
    assert tuple(result.result_id for result in results) == ("result-a", "result-b")
    assert first.calls == [enriched_event]
    assert second.calls == [enriched_event]


def test_executor_raises_for_invalid_event(registry):
    with pytest.raises(TypeError, match="event"):
        RuleEngineExecutor(registry, RegistryModuleLoader(registry)).execute(None)  # type: ignore[arg-type]


def test_executor_wraps_module_failure(registry, enriched_event):
    registry.register(StubModule("broken", failure=RuntimeError("failure")))
    with pytest.raises(ModuleExecutionError, match="broken") as error:
        RuleEngineExecutor(registry, RegistryModuleLoader(registry)).execute(enriched_event)
    assert isinstance(error.value.__cause__, RuntimeError)
