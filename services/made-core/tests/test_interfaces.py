from decimal import Decimal

import pytest

from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult


def test_detection_module_is_abstract():
    with pytest.raises(TypeError):
        DetectionModule()


def test_detection_module_uses_the_canonical_contract(timestamp):
    class FixtureModule(DetectionModule):
        def get_module_id(self) -> str:
            return "fixture-module"

        def detect(self, event) -> DetectionResult:
            return DetectionResult(
                result_id="result-1", event_id=event.event_id, module_id=self.get_module_id(),
                timestamp=event.timestamp, asset=event.asset, metric_value=Decimal("0"),
                threshold=Decimal("1"), anomaly_ratio=Decimal("0"), status="NORMAL", persistence=0,
            )

    assert issubclass(FixtureModule, DetectionModule)
