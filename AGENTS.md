# Repository Instructions

This repository contains 0DTE Liquidity Hunter, a local-first paper-trading research dashboard.

- Do not add live brokerage order execution.
- Do not use LLMs to generate market signals; signal rules must be deterministic and auditable.
- Keep mock, delayed, and live data status explicit in UI and API responses.
- Store secrets only in environment variables and keep `.env.example` safe.
- Run backend tests before committing backend changes.
