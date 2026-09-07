# MADE Canonical Data Contracts & API Specification

This document defines the canonical domain models, streaming schemas, and REST API endpoints used across the MADE system.

---

## 1. Domain Event Lifecycle

```text
NormalizedEvent → EnrichedEvent → DetectionResult → AggregatedResult → Alert
```

### 1.1 `NormalizedEvent`
- **Fields**:
  - `event_id` (str): Unique event identifier (e.g. `binance:btcusdt:spot:1700000000000`).
  - `timestamp` (datetime UTC): Event observation timestamp.
  - `source` (EventSource): `BINANCE`, `BYBIT`, `DEX`.
  - `market_type` (MarketType): `SPOT`, `FUTURES`, `DEX`.
  - `asset` (str): Base asset code (e.g. `BTC`, `ETH`).
  - `symbol` (str): Trading pair symbol (e.g. `BTCUSDT`).
  - `price` (Decimal): Current trade/index price.
  - `bid` (Decimal): Best bid price.
  - `ask` (Decimal): Best ask price.
  - `volume` (Decimal): 24h rolling volume.
  - `metadata` (dict): Optional additional properties (e.g. `funding_rate`).

### 1.2 `DetectionResult`
- **Fields**:
  - `result_id` (str): Unique result identifier.
  - `event_id` (str): Originating event ID.
  - `module_id` (str): Unique identifier of the evaluating module.
  - `timestamp` (datetime UTC): Detection timestamp.
  - `asset` (str): Evaluated asset.
  - `metric_value` (Decimal): Calculated metric value (e.g. spread percentage).
  - `threshold` (Decimal): Configured anomaly threshold.
  - `anomaly_ratio` (Decimal): Ratio `metric_value / threshold`.
  - `status` (ResultStatus): `NORMAL` or `ANOMALY`.
  - `persistence` (bool): Whether anomaly persists over the observation window.
  - `metadata` (dict): Additional module execution details.

### 1.3 `AggregatedResult`
- **Fields**:
  - `aggregation_id` (str): Unique aggregation identifier.
  - `asset` (str): Asset evaluated across modules.
  - `timestamp` (datetime UTC): Aggregation timestamp.
  - `correlation_window` (int): Temporal window in seconds.
  - `triggered_modules` (tuple[str, ...]): List of module IDs that reported `ANOMALY`.
  - `module_count` (int): Count of triggered modules.
  - `composite_anomaly_score` (Decimal): Aggregated anomaly score.
  - `max_anomaly_ratio` (Decimal): Maximum anomaly ratio among triggered modules.
  - `average_anomaly_ratio` (Decimal): Mean anomaly ratio.
  - `priority` (Priority): Evaluated priority (`HIGH`, `MEDIUM`, `LOW`).
  - `source_results` (tuple[DetectionResult, ...]): Underlying module detection results.

### 1.4 `Alert`
- **Fields**:
  - `alert_id` (str): Unique alert identifier.
  - `timestamp` (datetime UTC): Alert creation timestamp.
  - `asset` (str): Anomaly asset.
  - `priority` (Priority): `HIGH`, `MEDIUM`, `LOW`.
  - `title` (str): Human-readable alert title.
  - `summary` (str): Concise anomaly description.
  - `anomaly_score` (Decimal): Composite anomaly score.
  - `triggered_modules` (tuple[str, ...]): List of modules detecting anomaly.
  - `details` (dict): Full metadata and context payload.

---

## 2. FastAPI REST API Specification

Base URL: `http://localhost:8000/api/v1`

| Method | Endpoint | Description | Query Parameters |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Basic liveness probe | — |
| `GET` | `/ready` | Deep readiness probe (checks PostgreSQL) | — |
| `GET` | `/metrics` | System-wide statistics and counts | — |
| `GET` | `/modules` | List of registered MVP detection modules | — |
| `GET` | `/events` | Paginated stream of processed market events | `limit`, `offset`, `asset`, `source`, `market_type`, `status` |
| `GET` | `/events/{event_id}` | Detailed record of a single event | — |
| `GET` | `/detections` | Paginated module detection results | `limit`, `offset`, `module_id`, `status`, `asset` |
| `GET` | `/detections/{result_id}` | Single detection result details | — |
| `GET` | `/aggregates` | Aggregated multi-module anomaly candidate groups | `limit`, `offset`, `priority`, `asset` |
| `GET` | `/aggregates/{aggregation_id}`| Single aggregate entity with module details | — |
| `GET` | `/alerts` | High/Medium prioritized anomaly alerts | `limit`, `offset`, `priority`, `notification_status`, `asset` |
| `GET` | `/alerts/{alert_id}` | Detailed alert record with delivery metadata | — |
