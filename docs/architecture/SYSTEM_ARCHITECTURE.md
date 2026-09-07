# MADE System Architecture & Component Specification

This document details the high-level and component-level architecture of the **Modular Anomaly Detection Engine (MADE)** in accordance with the requirements for the master's qualification work (Specialty 123 "Computer Engineering").

---

## 1. High-Level System Flow

```mermaid
flowchart TD
    subgraph External Sources
        BN_S[Binance Spot WebSocket]
        BN_F[Binance Futures WebSocket]
        BB_S[Bybit Spot WebSocket]
        BB_F[Bybit Futures WebSocket]
    end

    subgraph Ingestion Layer [services/made-core: Ingestion Pipeline]
        COL[MultiSourceCollector]
        NORM[EventNormalizer]
        COL --> NORM
    end

    BN_S --> COL
    BN_F --> COL
    BB_S --> COL
    BB_F --> COL

    subgraph Event Bus [infra: Redis 7.0]
        RS[(Redis Streams\n'events:normalized')]
    end

    NORM -->|XADD| RS

    subgraph MADE Core Worker [services/made-core: Worker Process]
        CONS[RedisStreamConsumer\nConsumer Group: 'made-core-processors']
        VAL[NormalizedEventValidator]
        CACHE[SnapshotCache\nCross-Market State]
        ENR[DefaultContextEnricher]
        
        subgraph Rule Engine
            REG[InMemoryRuleRegistry]
            LOAD[RegistryModuleLoader]
            EXEC[RuleEngineExecutor]
            REG --> LOAD --> EXEC
        end

        subgraph Detection Modules [Deterministic Rules]
            M1[FuturesFuturesSpreadModule]
            M2[SpotFuturesSpreadModule]
            M3[DexFuturesSpreadModule]
            M4[FundingSpreadModule]
        end

        AGG[DefaultResultAggregator]
        CORR[DefaultCorrelationEngine]
        PRIO[DefaultPriorityEvaluator]
        ALERT_GEN[DefaultAlertGenerator]
    end

    RS -->|XREADGROUP / PEL| CONS
    CONS --> VAL
    VAL --> ENR
    CACHE -.->|Recent Snapshots| ENR
    ENR --> EXEC
    EXEC --> M1 & M2 & M3 & M4
    M1 & M2 & M3 & M4 --> AGG
    AGG --> CORR --> PRIO --> ALERT_GEN

    subgraph Persistence & Notification
        PG[(PostgreSQL 16\nDatabase)]
        TG[Telegram Bot API]
    end

    CONS -->|Persist Event, Detections, Aggregates, Alerts| PG
    ALERT_GEN -->|High/Medium Alerts| TG

    subgraph Presentation & API Layer
        API[FastAPI REST API Service\nservices/api: port 8000]
        DASH[React + Vite + MUI Dashboard\nweb-dashboard: port 3000]
    end

    PG <-->|Async SQLAlchemy / asyncpg| API
    API <-->|REST API HTTP / JSON| DASH
```

---

## 2. Component Roles and Boundaries

| Component | Directory / Service | Primary Responsibility | Architectural Rule |
| :--- | :--- | :--- | :--- |
| **Ingestion Pipeline** | `services/made-core/src/made_core/ingestion` | Ingest raw exchange streams, parse tickers, and normalise into canonical `NormalizedEvent`. | Isolated from detection logic; communicates exclusively via Redis Streams. |
| **MADE Core Worker** | `services/made-core/src/made_core/infrastructure/worker.py` | Consumes events from Redis, maintains `SnapshotCache`, enriches context, executes Rule Engine, aggregates results. | Stateless domain logic; no direct framework dependencies in modules. |
| **Detection Modules** | `services/made-core/src/made_core/modules` | 4 MVP deterministic rules: Spot-Futures, Futures-Futures, DEX-Futures, Funding-Spread. | Return `DetectionResult`; cannot create alerts, send notifications, or query DB directly. |
| **Persistence Adapter** | `services/made-core/src/made_core/infrastructure/postgres` | Idempotent persistence of events, detections, aggregates, and alerts into PostgreSQL. | Asynchronous SQLAlchemy 2.0 with connection pooling and Alembic schema management. |
| **FastAPI REST API** | `services/api` | Read-only REST API exposing paginated events, detections, aggregates, alerts, system metrics, and health checks. | Consumes PostgreSQL via `MadeQueryService`; completely decoupled from Core Worker. |
| **Web Dashboard** | `web-dashboard` | React 18 + Vite + TypeScript + Material UI interactive monitoring interface. | Communicates strictly via FastAPI REST API; zero direct connections to DB/Redis. |
| **Experimental Framework** | `experiments` | Scientific benchmarking suite measuring throughput, stratified latencies, fault recovery, and detection correctness. | Fully isolated test harnesses and reproducible seeded generators. |

---

## 3. Data Flow Progression

1. `NormalizedEvent`: Standardized market event from Redis Streams.
2. `EnrichedEvent`: Event augmented with `MarketContext` and recent `MarketSnapshot` items.
3. `DetectionResult`: Standardized output of a single detection module (`NORMAL` or `ANOMALY`).
4. `AggregatedResult`: Combined signals for one candidate anomaly (composite score, triggered modules).
5. `Alert`: Prioritized notification-ready entity (`HIGH`, `MEDIUM`, `LOW`).
