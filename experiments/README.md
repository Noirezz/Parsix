# MADE Experimental Evaluation and Benchmarking Framework

This package provides an isolated, reproducible, and scientifically rigorous benchmarking suite for the **Modular Anomaly Detection Engine (MADE)** in accordance with the Master's Qualification Work requirements (Specialty 123 "Computer Engineering").

## 1. Methodological Principles & Metric Boundaries

To ensure scientific defensibility, this framework enforces strict distinctions:
1. **Offered Load ($R_{\text{offered}}$)**: Rate-controlled event injection maintaining constant offered load via monotonic deadline pacing.
2. **Actual Throughput ($R_{\text{actual}}$)**: Successfully processed and committed events per second ($N_{\text{processed}} / T_{\text{measurement}}$), verified via PostgreSQL persistence confirmation.
3. **In-Memory Core Engine Capacity vs Live Throughput**:
   - *In-Memory Mode*: Pure CPU algorithmic processing capacity of the Rule Engine (events/sec).
   - *Live Mode*: Sustainable throughput across the full containerized stack (Redis Streams $\to$ Worker $\to$ PostgreSQL).
4. **Microsecond Stage Latency vs Controller-Observed Live Round-Trip**:
   - *Core Latency ($\mu\text{s}$)*: High-resolution monotonic timers measuring internal stages (Validation, Enrichment, Rule Engine, Aggregation).
   - *Live Round-Trip ($\text{ms}$)*: Controller-observed duration from Redis `XADD` publication to database persistence and REST API visibility.
5. **Real Empirical Fault Recovery (MTTR)**: Measured from fault injection ($T_{\text{fault}}$) to verifiable operational readiness ($T_{\text{recovery}}$) across real Docker container restarts and database reconnects.
6. **Warm-Up Sample Exclusion**: Initial warm-up events are excluded from steady-state latency percentiles.

---

## 2. CLI Usage & Reproducibility

### Full Benchmark Suite
```bash
python -m experiments.runners.benchmark_runner --experiment all --mode in-memory --seed 42 --trials 3
```

### Live Pipeline Throughput & Latency
```bash
# Live throughput with rate pacing across 50 eps
python -m experiments.runners.benchmark_runner --experiment throughput --mode live --rate 50 --duration 5.0 --trials 3

# Live round-trip latency
python -m experiments.runners.benchmark_runner --experiment latency --mode live --events 50 --trials 3

# Real failure recovery & MTTR
python -m experiments.runners.benchmark_runner --experiment failure --trials 3
```

---

## 3. Directory Structure

```text
experiments/
├── README.md                            # Comprehensive framework documentation
├── config/
│   ├── benchmark_config.yaml            # Workload, warm-up, and trial parameters
│   └── config_loader.py                 # Configuration parser and environment metadata
├── generators/
│   ├── synthetic_market_generator.py    # Seeded deterministic event generator
│   └── anomaly_generator.py             # Controlled anomaly scenario injector with ground truth
├── metrics/
│   ├── statistics.py                    # Statistical calculator (mean, percentiles p50..p99, F1)
│   └── collector.py                     # Monotonic latency recorder and Docker stats sampler
├── runners/
│   ├── benchmark_runner.py              # Unified CLI dispatcher
│   ├── accuracy_runner.py               # Detection accuracy evaluation runner
│   ├── latency_runner.py                # Dual-mode latency benchmark runner (in-memory & live)
│   ├── throughput_runner.py             # Dual-mode throughput benchmark runner (core & live)
│   ├── load_test_runner.py              # Staged stress & resource benchmark runner
│   └── failure_test_runner.py           # Real fault injection & MTTR runner
├── visualization/
│   └── plotter.py                       # Matplotlib publication chart generator (PNG & PDF)
├── results/
│   ├── raw/                             # Machine-readable JSON results
│   ├── csv/                             # Tabular latency and throughput CSVs
│   └── summary/                         # High-level aggregate reports
└── reports/
    └── figures/                         # Publication-quality vector (PDF) and bitmap (PNG) charts
```
