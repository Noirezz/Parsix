"""Production entrypoint for MADE Core Worker process."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from made_core.application.aggregator import DefaultResultAggregator
from made_core.application.alerting import DefaultAlertGenerator
from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
from made_core.application.correlation import DefaultCorrelationEngine
from made_core.application.enrichment import DefaultContextEnricher
from made_core.application.pipeline import EventPipeline
from made_core.application.priority import DefaultPriorityEvaluator
from made_core.application.rule_engine import (
    InMemoryRuleRegistry,
    RegistryModuleLoader,
    RuleEngineExecutor,
)
from made_core.application.validator import NormalizedEventValidator
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.infrastructure.redis_consumer import RedisStreamConsumer
from made_core.infrastructure.telegram.notifier import TelegramNotificationAdapter
from made_core.infrastructure.worker import MadeCoreWorker

from made_core.modules.dex_futures_spread import (
    DexFuturesSpreadConfig,
    DexFuturesSpreadModule,
)
from made_core.modules.funding_spread import (
    FundingSpreadConfig,
    FundingSpreadModule,
)
from made_core.modules.futures_futures_spread import (
    FuturesFuturesSpreadConfig,
    FuturesFuturesSpreadModule,
)
from made_core.modules.spot_futures_spread import (
    SpotFuturesSpreadConfig,
    SpotFuturesSpreadModule,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
)
logger = logging.getLogger("made_core.worker")


def create_default_worker(config: InfrastructureConfig | None = None) -> MadeCoreWorker:
    """Build a fully-configured MadeCoreWorker with all 4 MVP detection modules registered."""
    cfg = config or InfrastructureConfig()

    # 1. Rule Engine and MVP Detection Modules
    registry = InMemoryRuleRegistry()
    registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig()))
    registry.register(SpotFuturesSpreadModule(SpotFuturesSpreadConfig()))
    registry.register(DexFuturesSpreadModule(DexFuturesSpreadConfig()))
    registry.register(FundingSpreadModule(FundingSpreadConfig()))

    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry=registry, module_loader=loader)

    # 2. Upstream Core Pipeline
    validator = NormalizedEventValidator()
    enricher = DefaultContextEnricher()
    event_pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)

    # 3. Downstream Anomaly Processing Pipeline
    correlation_engine = DefaultCorrelationEngine()
    priority_evaluator = DefaultPriorityEvaluator()
    aggregator = DefaultResultAggregator(
        priority_evaluator=priority_evaluator,
        correlation_engine=correlation_engine,
    )
    alert_generator = DefaultAlertGenerator()
    anomaly_pipeline = AnomalyProcessingPipeline(
        aggregator=aggregator,
        correlation_engine=correlation_engine,
        priority_evaluator=priority_evaluator,
        alert_generator=alert_generator,
    )

    # 4. Infrastructure Adapters
    storage = PostgresStorageAdapter(config=cfg)
    telegram = TelegramNotificationAdapter(config=cfg)
    consumer = RedisStreamConsumer(
        event_pipeline=event_pipeline,
        anomaly_pipeline=anomaly_pipeline,
        config=cfg,
    )

    return MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipeline,
        anomaly_pipeline=anomaly_pipeline,
        storage=storage,
        telegram=telegram,
        config=cfg,
    )


async def main() -> None:
    """Entrypoint coroutine with signal handling for graceful shutdown."""
    logger.info("Initializing MADE Core Worker...")
    worker = create_default_worker()

    loop = asyncio.get_running_loop()

    def _signal_handler(sig: Any) -> None:
        logger.info("Received termination signal %s; shutting down gracefully...", sig)
        worker.stop()

    for sig_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, sig_name):
            try:
                loop.add_signal_handler(getattr(signal, sig_name), lambda s=sig_name: _signal_handler(s))
            except NotImplementedError:
                # Windows event loops do not support add_signal_handler
                signal.signal(getattr(signal, sig_name), lambda s, f: _signal_handler(s))

    async with worker:
        logger.info("MADE Core Worker started. Listening for stream events...")
        await worker.run()

    logger.info("MADE Core Worker stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker process exited.")
        sys.exit(0)
