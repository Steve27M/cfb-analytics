# Architecture

```mermaid
flowchart TD
    subgraph ingest["Ingestion (R)"]
        A[CFBD API<br/>cfbd_* endpoints] -->|budgeted, throttled, cached| B
        P[load_cfb_pbp<br/>quota-free, carries EPA/wp] --> B
        B[(DuckDB<br/>bronze.*<br/>raw · immutable · lineage)]
    end

    subgraph transform["Transform (dbt / SQL)"]
        B --> S[staging<br/>rename + recast]
        S --> SV[silver<br/>typed · deduped · conformed]
        SV --> G[(gold<br/>Kimball star + marts)]
        SV -.dbt snapshot.-> SCD[dim_team<br/>SCD2]
        SCD --> G
    end

    subgraph models["Models (R primary · Python parity)"]
        G --> M1[M1 stability]
        G --> M2[M2/M3 RYOE · lm]
        G --> M4[M4 CPOE · glm logistic]
        G --> M5[M5 passing-TD · Poisson]
        G --> M6[M6 PCA + clustering]
        G --> M7[M7 multilevel · lme4]
        M2 & M4 --> GM[Game model<br/>tidymodels · time-aware CV]
        M1 & M2 & M4 & M5 & M6 & M7 & GM -->|write back| GP[(gold.predictions<br/>gold.model_metrics<br/>gold.model_coefficients)]
    end

    GP --> DASH[Quarto dashboard<br/>data-eval + model-accuracy + R↔Python parity]

    ORCH[run.py orchestrator<br/>subprocess stages · fail-fast] -. drives .-> ingest
    ORCH -. drives .-> transform
    ORCH -. drives .-> models
    ORCH -. drives .-> DASH
```

**Polyglot contract:** R and Python exchange data **only** through the DuckDB warehouse
(`gold.*` tables + `artifacts/metrics.json`) — never in-memory. Killing the R stage fails the
pipeline cleanly.
