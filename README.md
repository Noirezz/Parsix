# MADE — Modular Anomaly Detection Engine

**MADE** is the core anomaly-detection mechanism for the master's qualification work in Computer Engineering, specialty 123 “Computer Engineering”:

> «Комп'ютерна система моніторингу потокових даних криптовалютної інфраструктури з модульним механізмом виявлення аномалій»

English title: **Computer System for Monitoring Streaming Data of Cryptocurrency Infrastructure with a Modular Anomaly Detection Mechanism**.

---

## 📑 Table of Contents

- [1. Project Purpose & Scientific Novelty](#1-project-purpose--scientific-novelty)
- [2. System Architecture](#2-system-architecture)
- [3. Fixed Technology Stack](#3-fixed-technology-stack)
- [4. Repository Structure & Navigation](#4-repository-structure--navigation)
- [5. MADE Core & Data Flow](#5-made-core--data-flow)
- [6. MVP Detection Modules](#6-mvp-detection-modules)
- [7. FastAPI REST API Service](#7-fastapi-rest-api-service)
- [8. Web Dashboard (React + Vite + MUI)](#8-web-dashboard-react--vite--mui)
- [9. Multi-Container Docker Compose Stack](#9-multi-container-docker-compose-stack)
- [10. Experimental Benchmarking Framework](#10-experimental-benchmarking-framework)
- [11. Testing & Verification](#11-testing--verification)
- [12. Architecture & Contracts Documentation](#12-architecture--contracts-documentation)

---

## 1. Project Purpose & Scientific Novelty

The system monitors streaming cryptocurrency-infrastructure data and identifies cross-market price and funding-rate anomalies across heterogeneous sources. MADE uses a unified event-processing model and independently replaceable, deterministic detection modules.

### Scientific Novelty
> «Удосконалено метод виявлення аномалій у потокових даних криптовалютної інфраструктури, який відрізняється використанням модульної архітектури незалежних компонентів аналізу подій та уніфікованої моделі оброблення даних, що дозволяє розширювати функціональні можливості системи шляхом додавання нових модулів без зміни її базової архітектури та забезпечує підвищення масштабованості програмного комплексу.»

The MVP is deterministic, rule- and threshold-based. It does not use machine learning, neural networks, or black-box classifiers in the real-time core pipeline.

---

## 2. System Architecture

```text
External Data Sources (Binance / Bybit)
  → MultiSource Ingestion Pipeline (Collector + Normalizer)
  → Redis Streams Event Bus ('events:normalized')
  → MADE Core Worker Process (SnapshotCache + Rule Engine + Aggregator)
  → PostgreSQL Database & Telegram Bot API
  → FastAPI REST API Service (port 8000)
  → React + Vite + MUI Web Dashboard (port 3000)
```

---

## 3. Fixed Technology Stack

| Area | Technology |
| :--- | :--- |
| **Backend & API** | Python 3.13+, FastAPI, REST, OpenAPI / Swagger |
| **Validation / Schemas** | Pydantic 2.x |
| **Database & ORM** | PostgreSQL 16, SQLAlchemy 2.x (asyncpg), Alembic migrations |
| **Streaming Transport** | Redis 7.0 Streams (Consumer Groups, PEL) |
| **Frontend Dashboard** | React 18, Vite, TypeScript, Material UI (MUI) |
| **Notifications** | Telegram Bot API |
| **Containerization** | Docker, Docker Compose |
| **Testing** | pytest, pytest-asyncio, vitest |
| **Documentation & Modeling** | PlantUML, Mermaid, KaTeX |

---

## 4. Repository Structure & Navigation

The repository is organized cleanly into decoupled services, infrastructure, documentation, and evaluation suites:

```text
Parsix/
├── docs/                                # Architecture and design documentation
│   ├── architecture/
│   │   └── SYSTEM_ARCHITECTURE.md       # High-level architecture & PlantUML/Mermaid diagrams
│   ├── contracts/
│   │   └── DATA_FLOW_CONTRACTS.md       # Domain event models & REST API specification
│   └── decisions/
│       └── ARCHITECTURE_DECISIONS.md    # Architecture Decision Records (ADRs)
├── services/                            # Backend services
│   ├── made-core/                       # Core domain, rule engine, modules, ingestion & storage
│   │   ├── Dockerfile
│   │   ├── src/made_core/
│   │   │   ├── domain/                  # NormalizedEvent, EnrichedEvent, DetectionResult, Alert
│   │   │   ├── application/             # Validator, Enricher, Rule Engine, Aggregator, Alerting
│   │   │   ├── modules/                 # 4 MVP modules (Spot-Futures, Futures-Futures, DEX, Funding)
│   │   │   ├── ingestion/               # Binance/Bybit Collectors, Normalizers & Ingestion Pipeline
│   │   │   └── infrastructure/          # Redis consumer/publisher, Postgres repository, Telegram
│   │   └── tests/                       # Unit and E2E integration tests (356 tests)
│   └── api/                             # FastAPI read-only REST API service
│       ├── Dockerfile
│       ├── src/made_api/                # Routers, Pydantic schemas, MadeQueryService
│       └── tests/                       # API mock and Postgres integration tests (17 tests)
├── web-dashboard/                       # Frontend Single Page Application
│   ├── Dockerfile & nginx.conf
│   ├── src/                             # React 18 + TypeScript + Material UI components & pages
│   └── tests/                           # Vitest component and page tests (14 tests)
├── experiments/                         # Scientific evaluation & benchmarking framework
│   ├── README.md                        # Experimental methodology & usage guide
│   ├── config/                          # Benchmark configuration & loader
│   ├── generators/                      # Seeded synthetic market & anomaly generators
│   ├── metrics/                         # Latency collectors, percentiles & classification metrics
│   ├── runners/                         # Throughput, latency, failure & accuracy runners
│   ├── visualization/                   # Matplotlib publication chart generator (plotter.py)
│   ├── results/                         # Raw JSON, tabular CSVs & summary reports
│   └── reports/figures/                 # Generated publication charts (PNG + vector PDF)
├── infra/                               # Deployment & database configuration
│   ├── compose/
│   │   └── docker-compose.yml           # Multi-container orchestration (6 services)
│   └── database/
│       ├── alembic.ini                  # Alembic migration configuration
│       └── alembic/versions/            # Versioned SQL migrations (initial schema)
├── pyproject.toml                       # Python project configuration & dependencies
├── AGENTS.md                            # Authoritative project architectural contract
└── README.md                            # Main project overview & documentation
```

---

## 5. MADE Core & Data Flow

```text
NormalizedEvent
  → Validation Layer
  → Context Enrichment (via SnapshotCache)
  → Rule Executor
  → active Detection Modules (4 MVP rules)
  → DetectionResult[]
  → Result Aggregator
  → Correlation Engine
  → Priority Evaluator
  → Alert Generator
  → Alert
```

**Canonical Model Progression**:
```text
NormalizedEvent → EnrichedEvent → DetectionResult → AggregatedResult → Alert
```

---

## 6. MVP Detection Modules

| Module | Identifier | Detection Formula |
| :--- | :--- | :--- |
| **Futures + Futures Spread** | `FuturesFuturesSpreadModule` | $\text{Spread} = \frac{\|P_1 - P_2\|}{P_{\text{ref}}} \times 100\%$ |
| **Spot + Futures Spread** | `SpotFuturesSpreadModule` | $\text{Spread} = \frac{\|P_{\text{spot}} - P_{\text{fut}}\|}{P_{\text{ref}}} \times 100\%$ |
| **DEX + Futures Spread** | `DexFuturesSpreadModule` | $\text{Spread} = \frac{\|P_{\text{dex}} - P_{\text{fut}}\|}{P_{\text{ref}}} \times 100\%$ |
| **Funding Spread** | `FundingSpreadModule` | $\Delta \text{Funding} = \|\text{FR}_1 - \text{FR}_2\|$ |

---

## 7. FastAPI REST API Service

The read-only REST API is hosted at `http://localhost:8000/api/v1` and provides structured endpoints for events, detections, aggregates, alerts, metrics, and health:

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Readiness Probe**: [http://localhost:8000/ready](http://localhost:8000/ready)
- **System Metrics**: [http://localhost:8000/api/v1/metrics](http://localhost:8000/api/v1/metrics)

---

## 8. Web Dashboard (React + Vite + MUI)

The Web Dashboard is hosted at `http://localhost:3000` and displays real-time telemetry:

- **Overview Page (`/`)**: System KPIs, event counters, recent alerts and detections.
- **Alerts Page (`/alerts`)**: Prioritized alerts with filtering by asset and priority (`HIGH`, `MEDIUM`, `LOW`).
- **Detections Page (`/detections`)**: Module-level detection results with metric values and anomaly ratios.
- **Aggregates Page (`/aggregates`)**: Candidate anomaly groupings.
- **Modules Page (`/modules`)**: Active modules registered in the Rule Registry.
- **Metrics Page (`/metrics`)**: Operational breakdowns and distributions.

---

## 9. Multi-Container Docker Compose Stack

Start all 6 services with a single command:

```bash
# Start stack in background
docker compose -f infra/compose/docker-compose.yml up -d

# Verify container status
docker compose -f infra/compose/docker-compose.yml ps
```

| Container | Service | Port | Function |
| :--- | :--- | :--- | :--- |
| `made-redis` | `redis` | `6379` | Redis 7 event streaming bus |
| `made-postgres` | `postgres` | `5432` | PostgreSQL 16 persistent database |
| `made-core-worker` | `made-core-worker` | — | Stream consumer & anomaly detection engine |
| `made-ingestion` | `made-ingestion` | — | Continuous multi-source ingestion for Binance & Bybit |
| `made-api` | `made-api` | `8000` | FastAPI read-only REST API |
| `made-dashboard` | `made-dashboard` | `3000` | React + Vite + MUI Web Dashboard |

---

## 10. Experimental Benchmarking Framework

Run reproducible scientific benchmarks for the master's thesis:

```bash
# Run all benchmark suites with default seed
python -m experiments.runners.benchmark_runner --experiment all --seed 42 --trials 3

# Run individual benchmarks
python -m experiments.runners.benchmark_runner --experiment accuracy --events 200 --seed 42
python -m experiments.runners.benchmark_runner --experiment latency --mode in-memory --events 500 --seed 42
python -m experiments.runners.benchmark_runner --experiment throughput --mode live --rate 10 --seed 42
python -m experiments.runners.benchmark_runner --experiment failure --trials 3 --seed 42
python -m experiments.runners.benchmark_runner --experiment plots
```

Scientific Results: [`experiments/results/summary/benchmark_report.md`](experiments/results/summary/benchmark_report.md)

---

## 11. Testing & Verification

The system maintains 100% test coverage across all domain contracts, modules, pipelines, and UI components:

```bash
# Run all backend unit and integration tests (373 tests)
pytest -v

# Run frontend tests (14 tests)
npm --prefix web-dashboard test

# Build frontend production bundle
npm --prefix web-dashboard run build
```

---

## 12. Architecture & Contracts Documentation

- [System Architecture & Component Specification](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Canonical Data Contracts & REST API Specification](docs/contracts/DATA_FLOW_CONTRACTS.md)
- [Architecture Decision Records (ADRs)](docs/decisions/ARCHITECTURE_DECISIONS.md)
- [Independent Scientific Audit Report (V4.0)](experiments/results/summary/methodology_audit_v4.md)
- [Master Thesis Scientific Benchmark Report](experiments/results/summary/benchmark_report.md)
- [Authoritative Project Charter (AGENTS.md)](AGENTS.md)
