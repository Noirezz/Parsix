from made_core.domain.enums import (
    EventSource,
    MarketType,
    Priority,
    ReferencePriceMode,
    ResultStatus,
    ValidationStatus,
)
from made_core.domain.interfaces import (
    AlertGenerator,
    ContextEnricher,
    CorrelationEngine,
    DetectionModule,
    EventValidator,
    ModuleLoader,
    PriorityEvaluator,
    ResultAggregator,
    RuleExecutor,
    RuleRegistry,
)
from made_core.domain.models import (
    AggregatedResult,
    Alert,
    CorrelatedGroup,
    DetectionResult,
    EnrichedEvent,
    MarketContext,
    MarketSnapshot,
    NormalizedEvent,
    PipelineExecutionResult,
    RawEvent,
    ValidationError,
    ValidationResult,
)
from made_core.application.alerting import DefaultAlertGenerator
from made_core.application.aggregator import DefaultResultAggregator
from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
from made_core.application.correlation import DefaultCorrelationEngine
from made_core.application.enrichment import DefaultContextEnricher
from made_core.application.pipeline import EventPipeline
from made_core.application.priority import DefaultPriorityEvaluator
from made_core.application.rule_engine import InMemoryRuleRegistry, RegistryModuleLoader, RuleEngineExecutor
from made_core.application.validator import NormalizedEventValidator
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres import PostgresStorageAdapter
from made_core.infrastructure.redis_consumer import RedisStreamConsumer
from made_core.infrastructure.telegram import TelegramNotificationAdapter
from made_core.infrastructure.worker import MadeCoreWorker

from made_core.ingestion.collector import BinanceCollector, CollectorConfig
from made_core.ingestion.normalizer import BinanceNormalizer
from made_core.ingestion.pipeline import IngestionPipeline
from made_core.ingestion.publisher import RedisEventPublisher



from made_core.modules.dex_futures_spread import DexFuturesSpreadConfig, DexFuturesSpreadModule
from made_core.modules.funding_spread import FundingSpreadConfig, FundingSpreadModule
from made_core.modules.futures_futures_spread import FuturesFuturesSpreadConfig, FuturesFuturesSpreadModule
from made_core.modules.spot_futures_spread import SpotFuturesSpreadConfig, SpotFuturesSpreadModule

__all__ = [
    "AggregatedResult",
    "Alert",
    "AlertGenerator",
    "AnomalyProcessingPipeline",
    "BinanceCollector",
    "BinanceNormalizer",
    "CollectorConfig",
    "CorrelatedGroup",
    "CorrelationEngine",
    "ContextEnricher",
    "DefaultAlertGenerator",
    "DefaultContextEnricher",
    "DefaultCorrelationEngine",
    "DefaultPriorityEvaluator",
    "DefaultResultAggregator",
    "DetectionModule",
    "DetectionResult",
    "DexFuturesSpreadConfig",
    "DexFuturesSpreadModule",
    "EnrichedEvent",
    "EventPipeline",
    "EventSource",
    "EventValidator",
    "FundingSpreadConfig",
    "FundingSpreadModule",
    "FuturesFuturesSpreadConfig",
    "FuturesFuturesSpreadModule",
    "InMemoryRuleRegistry",
    "InfrastructureConfig",
    "IngestionPipeline",
    "MadeCoreWorker",
    "MarketContext",
    "MarketSnapshot",
    "MarketType",
    "ModuleLoader",
    "NormalizedEvent",
    "NormalizedEventValidator",
    "PipelineExecutionResult",
    "PostgresStorageAdapter",
    "Priority",
    "PriorityEvaluator",
    "RawEvent",
    "RedisEventPublisher",
    "RedisStreamConsumer",
    "ReferencePriceMode",
    "RegistryModuleLoader",
    "ResultAggregator",
    "ResultStatus",
    "RuleEngineExecutor",
    "RuleExecutor",
    "RuleRegistry",
    "SpotFuturesSpreadConfig",
    "SpotFuturesSpreadModule",
    "TelegramNotificationAdapter",
    "ValidationError",
    "ValidationResult",
    "ValidationStatus",
]
