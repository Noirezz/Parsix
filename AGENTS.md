# AGENTS.md — MADE implementation contract

## 1. Project identity

**MADE** means **Modular Anomaly Detection Engine**. It is the core anomaly-detection mechanism of the master's qualification work in Computer Engineering, specialty 123 “Computer Engineering”:

> “Комп'ютерна система моніторингу потокових даних криптовалютної інфраструктури з модульним механізмом виявлення аномалій”

English project name: **Computer System for Monitoring Streaming Data of Cryptocurrency Infrastructure with a Modular Anomaly Detection Mechanism**.

The system monitors streaming cryptocurrency-infrastructure data and detects anomalies with independent, deterministic, rule- and threshold-based modules operating on a common event model.

### Scientific contribution to preserve

The agreed scientific novelty is:

> “Удосконалено метод виявлення аномалій у потокових даних криптовалютної інфраструктури, який відрізняється використанням модульної архітектури незалежних компонентів аналізу подій та уніфікованої моделі оброблення даних, що дозволяє розширювати функціональні можливості системи шляхом додавання нових модулів без зміни її базової архітектури та забезпечує підвищення масштабованості програмного комплексу.”

Do not describe MADE as AI, machine learning, intelligent analysis, a neural-network system, forecasting, or automated model scoring. Those approaches are not part of the MVP or agreed architecture.

## 2. Fixed technology stack

The following are fixed architectural decisions:

| Area | Required technology |
| --- | --- |
| Backend | Python 3.13+, FastAPI |
| Validation and schemas | Pydantic 2.x |
| Database | PostgreSQL |
| ORM | SQLAlchemy 2.x |
| Database migrations | Alembic |
| Event bus / streaming transport | Redis Streams |
| Frontend | React, Vite, Material UI (MUI) |
| Notifications | Telegram Bot API |
| Containerization | Docker, Docker Compose |
| Testing | pytest |
| API | REST; OpenAPI / Swagger through FastAPI |
| UML and architecture documentation | PlantUML |

Do not replace or supplement these decisions with Node.js, NestJS, Express, Django, MongoDB, MySQL, Kafka, RabbitMQ, Celery, another frontend/UI framework, or another notification platform. Do not introduce additional infrastructure technologies unless the project owner explicitly approves them. If a needed technical decision is not listed, stop and ask for approval.

## 3. Fixed system boundary and architecture

The full system flow is fixed:

```text
External Data Sources
  → Collector Service
  → Normalizer Service
  → Redis Streams
  → MADE Core
  → Storage Service / REST API / Notification Service / Web Dashboard
```

The major components are Collector Service, Normalizer Service, Redis Streams Event Bus, MADE Core, Storage Service, REST API, Notification Service, Web Dashboard, and PostgreSQL.

Do not add an API Gateway, message-broker abstraction service, Module Manager, AI/ML service, or other major architectural component without explicit approval.

## 4. Fixed MADE Core architecture

`MADE Core` contains exactly these logical components:

```text
Validation Layer
Context Enrichment
Rule Engine
  ├─ Rule Registry
  ├─ Module Loader
  └─ Rule Executor
Detection Modules
Result Aggregator
Correlation Engine
Priority Evaluator
Alert Generator
Metrics Collector
```

There is **no separate Module Manager**. Module registration, discovery/loading, selection, and execution belong to the Rule Engine:

```text
Rule Registry → Module Loader → Rule Executor
```

Do not hard-code a sequential chain of individual modules in the core pipeline.

## 5. Canonical data flow and contracts

Use these names consistently in code, API contracts, tests, diagrams, and documentation:

```text
NormalizedEvent → EnrichedEvent → DetectionResult → AggregatedResult → Alert
```

| Stage | Canonical model | Responsibility |
| --- | --- | --- |
| Input | `NormalizedEvent` | Standardised market event from Redis Streams |
| Enrichment | `EnrichedEvent` | Event plus market context and calculated metrics |
| Module output | `DetectionResult` | Standardised result of one module |
| Aggregation | `AggregatedResult` | Combined signals for one candidate anomaly |
| Output | `Alert` | Prioritised notification-ready anomaly |

Supporting models may include `MarketContext`, `MarketSnapshot`, and `CorrelatedGroup`. Follow the agreed UML class model; do not arbitrarily introduce alternative domain models.

### `NormalizedEvent`

Required logical fields: `eventId`, `timestamp`, `source`, `marketType`, `asset`, `symbol`, `price`, `bid`, `ask`, `volume`, `metadata`.

`marketType` is one of `SPOT`, `FUTURES`, `DEX`. The event source is represented by `EventSource`.

### `EnrichedEvent`

Contains `eventId`, `timestamp`, `asset`, `marketContext`, `normalizedData`, `referenceData`, `calculatedMetrics`, and `metadata`. `MarketContext` contains applicable `MarketSnapshot` values for an asset/symbol at a timestamp.

### `DetectionResult`

Every module returns this model, including when it finds no anomaly. Required logical fields: `resultId`, `eventId`, `moduleId`, `timestamp`, `asset`, `metricValue`, `threshold`, `anomalyRatio`, `status`, `persistence`, `metadata`. `status` is `NORMAL` or `ANOMALY`.

### `AggregatedResult` and `Alert`

`AggregatedResult` includes `aggregationId`, `asset`, `timestamp`, `correlationWindow`, `triggeredModules`, `moduleCount`, `compositeAnomalyScore`, `maxAnomalyRatio`, `averageAnomalyRatio`, `priority`, `sourceResults`, `metadata`.

`Alert` includes `alertId`, `timestamp`, `asset`, `priority`, `title`, `summary`, `anomalyScore`, `triggeredModules`, `details`. Priority values are `LOW`, `MEDIUM`, and `HIGH`.

The execution flow inside MADE is:

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

An invalid event stops at validation. If aggregation finds no anomaly, correlation, priority evaluation, and alert generation do not run. A result below the configured alerting priority is not converted into an alert.

## 6. Module contract and MVP scope

The central extension point is `DetectionModule`:

```text
getModuleId(): String
detect(event: EnrichedEvent): DetectionResult
```

Every module must have a stable, unique `moduleId`; accept only `EnrichedEvent`; return only `DetectionResult`; remain independently testable; and not create `Alert` objects, send notifications, write to the dashboard, depend on other modules' internal logic, or couple directly to Redis, PostgreSQL, Telegram, or FastAPI.

The MVP contains exactly these four modules:

| Module | Purpose |
| --- | --- |
| `FuturesFuturesSpreadModule` | Anomalous price difference for the same trading pair across futures markets/exchanges. |
| `SpotFuturesSpreadModule` | Anomalous price difference between spot and futures markets for the same asset/pair. |
| `DexFuturesSpreadModule` | Anomalous price difference between DEX market data and futures market data for the same asset/pair. |
| `FundingSpreadModule` | Anomalous funding-rate difference between futures markets; not a general-purpose funding monitor. |

Do not add modules without explicit approval. Future modules may be documented as future extensions only.

For price-spread modules:

```text
Spread = |P1 - P2| / Pref × 100%

if Spread >= Threshold:
    status = ANOMALY
else:
    status = NORMAL
```

Thresholds must be configurable. `referencePriceMode` is configuration, not a core component; its allowed values are `FIRST`, `SECOND`, `AVERAGE`, and `LAST`.

## 7. Component responsibilities and repository principles

| Component | Must do | Must not do |
| --- | --- | --- |
| Validation Layer | Validate fields, types, timestamps, sources, symbols, and numeric values. | Detect anomalies. |
| Context Enrichment | Build the market context required by modules. | Apply module-specific alerting logic. |
| Rule Registry | Hold module metadata and availability. | Execute detection algorithms. |
| Module Loader | Resolve registered modules for execution. | Become a service/manager. |
| Rule Executor | Select applicable active modules and execute them independently. | Contain module-specific formulas. |
| Detection Modules | Produce independent `DetectionResult` values. | Generate final alerts. |
| Result Aggregator | Combine standardised results. | Inspect private module details. |
| Correlation Engine | Group related results by asset, time window, sources, and modules. | Replace aggregation or generate notifications. |
| Priority Evaluator | Assign `LOW`, `MEDIUM`, or `HIGH`. | Read raw exchange payloads. |
| Alert Generator | Transform an aggregate into an `Alert`. | Know module internals. |
| Metrics Collector | Record operational metrics. | Change a detection decision. |

Maintain a clear separation of domain, application/core logic, infrastructure, interfaces, detection modules, and tests. Domain logic must remain independent of PostgreSQL, Redis, Telegram, HTTP frameworks, and external exchange clients. Infrastructure adapters implement application/domain contracts; prefer dependency inversion and explicit interfaces where appropriate.

## 8. Implementation rules and non-goals

- Use explicit domain types/enums for market type, status, priority, source, and reference-price mode.
- Keep data-source collection and payload normalisation outside MADE Core.
- Make thresholds, correlation windows, and priority rules traceable and testable.
- Use deterministic financial calculations with clear rounding/precision rules.
- Log validation and processing failures with an event/module correlation identifier; do not silently discard them.
- When creating a domain service or module, add pytest unit tests for normal, threshold-boundary, anomaly, and insufficient-context cases.
- Update `README.md` whenever a public contract, service boundary, module list, startup procedure, or implementation status changes.

MVP non-goals: trained models; neural networks; model training; forecasting; automated scoring; a Module Manager; extra detection modules; exchange-specific detection logic inside MADE Core; collector-to-dashboard bypasses of Redis Streams and MADE; alerts created directly by modules; and a general-purpose funding-rate monitor.

## 9. Architectural-change policy

`AGENTS.md` is the authoritative instruction file for Codex. If a future request conflicts with this contract, identify the conflict and ask for clarification before making the change.

Explicit project-owner approval is required before changing the programming language, backend framework, database, event bus, frontend framework, notification mechanism, containerization approach, MADE Core structure, domain data-flow model, `DetectionModule` contract, MVP modules, major services, Rule Registry / Module Loader / Rule Executor, or before introducing a Module Manager or AI/ML components.

If implementation is difficult under the fixed architecture, explain the issue and propose alternatives, but do not make an architectural change without approval.

## 10. Delivery checklist

Before completing an implementation change, verify:

1. It respects the fixed component boundaries and MVP scope.
2. Public contracts remain canonical.
3. A module can be registered and run without modifying unrelated core components.
4. Invalid, no-anomaly, and low-priority paths do not produce alerts.
5. Tests cover the changed deterministic rule or contract.
6. Documentation and configuration describe any new threshold or operational setting.
