# OKX Quant Lab Visual Summary

This is the one-page map of what we have built so far.

Read it from left to right: data comes in, research code tests ideas, reports explain results, and Freqtrade gives us a safe bot-framework sandbox.

## System Map

```mermaid
flowchart LR
    You["You, beginner researcher"] --> Lab["Our OKX quant lab"]
    You --> FT["Freqtrade dry-run lab"]

    OKXPublic["OKX public market data"] --> Candles["Local candle CSV files"]
    Candles --> Backtest["Backtests"]
    Candles --> Paper["Local paper state"]
    Candles --> Scan["Multi-market scans"]

    Lab --> Fetch["Fetch public candles"]
    Fetch --> Candles
    Backtest --> Reports["Markdown reports"]
    Backtest --> Dashboard["Static demo dashboard"]
    Paper --> Reports
    Scan --> Reports

    FT --> FTConfig["Safe config"]
    FT --> FTStrategy["OKXLabDryRunStrategy"]
    FTConfig --> FTBot["Freqtrade container"]
    FTStrategy --> FTBot
    FTBot --> FreqUI["FreqUI at 127.0.0.1:8080"]
    FTBot --> FTDB["Local SQLite dry-run database"]
    FTBot --> FTLogs["Local logs"]

    Secrets["API keys and private account access"] -. blocked .-> Live["Live orders"]
    FTBot -. no keys .-> Secrets
    Lab -. no keys .-> Secrets

    classDef safe fill:#e8f5ee,stroke:#20835a,color:#123;
    classDef caution fill:#fff7df,stroke:#a66a00,color:#222;
    classDef blocked fill:#ffe8e8,stroke:#b33a3a,color:#222;

    class OKXPublic,Candles,Backtest,Paper,Scan,Reports,Dashboard,FTConfig,FTStrategy,FTBot,FreqUI,FTDB,FTLogs safe;
    class You,Lab,FT caution;
    class Secrets,Live blocked;
```

## Safety Boundary

```mermaid
flowchart TD
    Safe["Safe now"] --> PublicData["Public OKX candles"]
    Safe --> LocalFiles["Local CSV, JSON, reports"]
    Safe --> Backtests["Backtests with fees and slippage"]
    Safe --> PaperTrading["Local paper trading"]
    Safe --> FreqDryRun["Freqtrade dry-run, bot stopped"]

    NeedsConfirm["Needs explicit confirmation later"] --> APIKeys["Create or use API keys"]
    NeedsConfirm --> OKXDemo["OKX demo trading through private API"]
    NeedsConfirm --> LiveTrading["Live trading with real funds"]
    NeedsConfirm --> Transfers["Transfers or account-security changes"]
    NeedsConfirm --> Leverage["Leverage or futures"]

    Safe -. separated from .-> NeedsConfirm

    classDef safe fill:#e8f5ee,stroke:#20835a,color:#123;
    classDef blocked fill:#ffe8e8,stroke:#b33a3a,color:#222;

    class Safe,PublicData,LocalFiles,Backtests,PaperTrading,FreqDryRun safe;
    class NeedsConfirm,APIKeys,OKXDemo,LiveTrading,Transfers,Leverage blocked;
```

## Learning Ladder

```mermaid
flowchart TD
    L1["1. Public market data"] --> L2["2. Simple backtest"]
    L2 --> L3["3. Add fees and slippage"]
    L3 --> L4["4. Save candles locally"]
    L4 --> L5["5. Parameter sweeps"]
    L5 --> L6["6. Walk-forward validation"]
    L6 --> L7["7. Risk and sizing"]
    L7 --> L8["8. Paper replay"]
    L8 --> L9["9. Monitoring reports"]
    L9 --> L10["10. Safe demo"]
    L10 --> L11["11. Freqtrade dry-run UI"]
    L11 --> L12["12. More research before demo API"]
    L12 --> L13["13. Demo trading only after confirmation"]
    L13 --> L14["14. Tiny live trading only much later"]
```

## Our Lab Compared With Freqtrade

```mermaid
flowchart LR
    subgraph OQL["Our OKX Lab"]
        O1["Small Python scripts"]
        O2["Transparent math"]
        O3["Beginner lessons"]
        O4["Custom reports"]
        O5["Good for learning internals"]
    end

    subgraph FTL["Freqtrade Dry-Run"]
        F1["Docker bot framework"]
        F2["Strategy class"]
        F3["Web UI"]
        F4["Local dry-run database"]
        F5["Good for learning operations"]
    end

    Shared["Shared strategy idea: SMA20 crosses SMA50"] --> O1
    Shared --> F2
    OQL --> Discipline["Same discipline: distrust results until fees, slippage, out-of-sample tests, and walk-forward checks"]
    FTL --> Discipline
```

## Current Safe Runtime

| Area | Current status |
| --- | --- |
| OKX lab | Public data and local simulation only |
| Safe demo | Generates Markdown and HTML reports |
| Freqtrade | Installed in Docker |
| Freqtrade version | `2026.5.1` |
| Freqtrade URL | `http://127.0.0.1:8080` |
| Freqtrade mode | `dry_run: true` |
| Freqtrade bot state | `stopped` |
| OKX credentials | Empty |
| Live orders | Not enabled |

## What Each Output Means

```mermaid
flowchart LR
    Scripts["Lesson scripts"] --> Explain["Teach one concept at a time"]
    Reports["Reports"] --> Read["Human-readable results"]
    Dashboard["Safe demo dashboard"] --> Inspect["Quick visual inspection"]
    PaperState["Paper JSON state"] --> Track["Fake cash, fake asset, fake fills"]
    FreqUI["FreqUI"] --> Operate["Bot-framework view of dry-run status"]
    Tests["Unit tests"] --> Guard["Catch simple regressions"]
```

## Beginner Rule Of Thumb

If a result looks profitable, the next move is not live trading.

The next move is:

```text
add costs -> split data -> test unseen periods -> walk-forward -> reduce size -> monitor -> paper trade longer
```

Only after that should we discuss demo API trading, and only with explicit confirmation.
