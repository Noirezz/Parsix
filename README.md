# MADE — Modular Anomaly Detection Engine

**MADE** is the core anomaly-detection mechanism for the master's qualification work in Computer Engineering, specialty 123 “Computer Engineering”:

> “Комп'ютерна система моніторингу потокових даних криптовалютної інфраструктури з модульним механізмом виявлення аномалій”

English title: **Computer System for Monitoring Streaming Data of Cryptocurrency Infrastructure with a Modular Anomaly Detection Mechanism**.

## Project purpose

The system will monitor streaming cryptocurrency-infrastructure data and identify price and funding-rate anomalies across market types and sources. MADE uses a unified event-processing model and independently replaceable, deterministic detection modules.

The MVP is rule- and threshold-based. It does not use AI, machine learning, neural networks, forecasting, LLM-based detection, or automated model scoring.

## Fixed system architecture

```text
External Data Sources
  → Collector Service
  → Normalizer Service
  → Redis Streams
  → MADE Core
  → Storage Service / REST API / Notification Service / Web Dashboard
```

The system comprises the Collector Service, Normalizer Service, Redis Streams Event Bus, MADE Core, Storage Service, REST API, Notification Service, Web Dashboard, and PostgreSQL. A separate API Gateway, Module Manager, AI/ML service, or message-broker abstraction service is not part of the architecture.

## Fixed technology stack

| Area | Technology |
| --- | --- |
| Backend and API | Python 3.13+, FastAPI, REST, OpenAPI / Swagger |
| Validation / schemas | Pydantic 2.x |
| Database / persistence | PostgreSQL, SQLAlchemy 2.x, Alembic |
| Streaming transport | Redis Streams |
| Frontend | React, Vite, Material UI (MUI) |
| Notifications | Telegram Bot API |
| Containerization | Docker, Docker Compose |
| Testing | pytest |
| Architecture documentation | PlantUML |

These are fixed design decisions. Alternative backend frameworks, databases, event buses, frontend/UI frameworks, and notification platforms are outside the current scope.

## MADE Core and data flow

MADE Core consists of Validation Layer, Context Enrichment, Rule Engine, Detection Modules, Result Aggregator, Correlation Engine, Priority Evaluator, Alert Generator, and Metrics Collector.

The Rule Engine contains `Rule Registry → Module Loader → Rule Executor`. There is no standalone `Module Manager`.

```text
NormalizedEvent
  → Validation Layer
  → Context Enrichment
  → Rule Executor
  → active Detection Modules
  → DetectionResult[]
  → Result Aggregator
  → Correlation Engine
  → Priority Evaluator
  → Alert Generator
  → Alert
```

The canonical model progression is:

```text
NormalizedEvent → EnrichedEvent → DetectionResult → AggregatedResult → Alert
```

Invalid events stop at validation. If no anomaly is aggregated, correlation, priority evaluation, and alert generation do not run. Results below the configured alerting priority are not converted into alerts.

## MVP detection modules

| Module | Detection target |
| --- | --- |
| Futures + Futures Spread Module (`FuturesFuturesSpreadModule`) | Price difference for the same pair across futures markets/exchanges. |
| Spot + Futures Spread Module (`SpotFuturesSpreadModule`) | Price difference between spot and futures markets for one asset/pair. |
| DEX + Futures Spread Module (`DexFuturesSpreadModule`) | Price difference between DEX and futures data for one asset/pair. |
| Funding Spread Module (`FundingSpreadModule`) | Funding-rate difference between futures markets; not a general funding monitor. |

Price-spread rules use the baseline calculation:

```text
Spread = |P1 - P2| / Pref × 100%
```

When the spread is at least the configured threshold, the module returns `ANOMALY`; otherwise it returns `NORMAL`. Thresholds and the reference-price mode (`FIRST`, `SECOND`, `AVERAGE`, or `LAST`) are configurable.

## Repository structure

The initial MADE Core domain package is implemented under `services/made-core/src/made_core`, with its unit tests under `services/made-core/tests`. The following remains the planned broader repository structure; it is not a claim that its remaining services are already implemented:

```text
docs/                  # PlantUML diagrams, decisions, contracts
services/
  collector/           # External data collection
  normalizer/          # Raw payload → NormalizedEvent
  made-core/           # Domain, application, modules, infrastructure, tests
  storage/             # Event/result/alert persistence
  api/                 # FastAPI REST API
  notification/        # Telegram delivery adapter
web-dashboard/         # React + Vite + MUI interface
config/                # Non-secret configuration
infra/                 # Redis, PostgreSQL, Docker Compose setup
```

The implementation will keep domain, application/core logic, infrastructure, interfaces, detection modules, and tests separate. Detection logic will not depend directly on Redis, PostgreSQL, Telegram, FastAPI, or exchange-client details.

## Development prerequisites and running

When implementation begins, the expected prerequisites will be Python 3.13+, Docker with Docker Compose, PostgreSQL, Redis, and a current Node.js runtime for the React/Vite dashboard.

The initial domain layer can be installed and verified with:

```text
python -m pip install -e ".[dev]"
python -m pytest -q
```

To run the complete containerized environment (Redis, PostgreSQL, and MADE Core Worker):

```bash
docker compose -f infra/compose/docker-compose.yml up -d
```

## Testing approach

The project uses `pytest`. Each deterministic detection module and domain service is covered with normal, threshold-boundary, anomaly, and insufficient-context unit cases. MADE Core also includes in-memory Rule Engine integration tests that execute registered detection modules through `RuleRegistry → ModuleLoader → RuleExecutor` without calling modules directly, including a focused modularity test that runs multiple real spread modules through one shared Rule Engine. Integration tests covering containerized Redis Streams, PostgreSQL persistence, concurrency, and Telegram mock delivery are categorized with the `@pytest.mark.integration` marker.

## Scope and future direction

**Current status:** the MADE Core domain models, enums, the infrastructure-independent Rule Engine mechanism (`RuleRegistry → ModuleLoader → RuleExecutor`), the Validation Layer MVP (`EventValidator` / `NormalizedEventValidator`), the Context Enrichment Layer MVP (`ContextEnricher` / `DefaultContextEnricher`), the Pipeline Orchestration Layer MVP (`EventPipeline` / `PipelineExecutionResult`), all four MVP detection modules (`FuturesFuturesSpreadModule`, `SpotFuturesSpreadModule`, `DexFuturesSpreadModule`, `FundingSpreadModule`), the Downstream Result-Processing Layer MVP (`DefaultCorrelationEngine`, `DefaultPriorityEvaluator`, `DefaultResultAggregator`, `DefaultAlertGenerator`, `AnomalyProcessingPipeline`), Infrastructure Phase 1 (`InfrastructureConfig`, `RedisStreamConsumer`), Infrastructure Phase 2 (`PostgresStorageAdapter`, SQLAlchemy 2.x declarative models, Alembic schema migrations), Infrastructure Phase 3 (`TelegramNotificationAdapter` via HTTP Bot API), Infrastructure Phase 4 (`MadeCoreWorker` end-to-end orchestration and idempotent notification state machine), Infrastructure Phase 5 (Docker Compose containerization and E2E integration test suite), and the Ingestion Layer (`BinanceCollector`, `BinanceNormalizer`, `RedisEventPublisher`, `IngestionPipeline`) are implemented and verified. Web Dashboard and REST API integrations are scheduled for subsequent phases.


**MVP scope:** the four spread modules above, standardised results, aggregation, correlation, priority evaluation, and alert generation within the fixed architecture.

**Future direction:** additional detection modules may be considered only as approved extensions. They must preserve the canonical data flow and be registered through the Rule Engine without changing the fundamental pipeline.

The authoritative implementation contract is [AGENTS.md](AGENTS.md).
