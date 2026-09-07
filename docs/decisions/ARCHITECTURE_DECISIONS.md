# Architecture Decision Records (ADR)

This document records the foundational architectural decisions for the MADE project (Specialty 123 "Computer Engineering").

---

## ADR-001: Deterministic Modular Anomaly Detection vs Machine Learning

- **Status**: Accepted
- **Context**: The master's thesis focuses on stream processing, modularity, and deterministic multi-market arbitrage/spread detection.
- **Decision**: All MVP detection modules (`FuturesFuturesSpreadModule`, `SpotFuturesSpreadModule`, `DexFuturesSpreadModule`, `FundingSpreadModule`) use deterministic threshold formulas. No AI/ML models, neural networks, or black-box classifiers are used in the core pipeline.
- **Consequences**: Deterministic, 100% reproducible anomaly detection with strict time complexity $O(1)$ per event and sub-millisecond in-memory execution latency.

---

## ADR-002: Technology Stack Selection

- **Status**: Accepted
- **Context**: Fixed stack defined in project charter (`AGENTS.md`).
- **Choices**:
  - **Backend**: Python 3.13+, FastAPI, Pydantic 2.x (high performance, async support, auto-generated OpenAPI).
  - **Transport / Event Bus**: Redis Streams (lightweight, microsecond latency, consumer groups, PEL replay capability).
  - **Database & ORM**: PostgreSQL 16 + SQLAlchemy 2.0 (asyncpg) + Alembic (ACID compliance, relational queries for aggregates, migrations).
  - **Frontend**: React 18 + Vite + TypeScript + Material UI (MUI) (modern component ecosystem, typed API integration).
  - **Containerization**: Docker Compose (single command multi-container bring-up).

---

## ADR-003: Pipeline Decoupling and Persistence Strategy

- **Status**: Accepted
- **Context**: High-frequency streaming events must not be blocked by UI queries.
- **Decision**: 
  - External ingestion writes directly to Redis Streams.
  - MADE Core Worker continuously processes streams and commits results to PostgreSQL.
  - FastAPI and React Web Dashboard read strictly from PostgreSQL asynchronously.
- **Consequences**: Zero contention between UI queries and real-time event processing. Clean boundary with complete service isolation.
