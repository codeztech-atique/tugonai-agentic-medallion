# Spec 07 — Question Harness

## Purpose

A curated set of questions to exercise **Schema** and **Quality** agents through Gateway → MCP → Supabase, plus a small STM memory check.

## Files

| Path | Role |
| --- | --- |
| [harness/questions.json](../harness/questions.json) | Question bank |
| [harness/run_harness.py](../harness/run_harness.py) | Runner (list / ask / interactive / batch) |
| [harness/ui/app.py](../harness/ui/app.py) | Local Agent Console UI |
| `harness/results/` | Saved transcripts (gitignored recommended) |

## Quick start

```bash
cd /Users/atique1201gmail.com/Desktop/Development/TugonAI
set -a && source .env && set +a

# Web UI (invoke agents visually)
/opt/homebrew/bin/python3.11 harness/ui/app.py
# → http://127.0.0.1:8765

# See all questions (no AWS calls)
/opt/homebrew/bin/python3.11 harness/run_harness.py list

# Ask one curated question
/opt/homebrew/bin/python3.11 harness/run_harness.py ask S3 --save
/opt/homebrew/bin/python3.11 harness/run_harness.py ask Q2 --save

# Free-form chat
/opt/homebrew/bin/python3.11 harness/run_harness.py interactive --agent schema

# Batch soft-scored run
/opt/homebrew/bin/python3.11 harness/run_harness.py batch --agent schema --ids S1,S2,S3
/opt/homebrew/bin/python3.11 harness/run_harness.py batch --agent quality --ids Q1,Q2,Q3
```

## Suggested ask order (demo)

1. **S1** — inventory (path works?)  
2. **S2** — sample messiness  
3. **S3** — silver DDL JSON  
4. **Q1** — profile bronze  
5. **Q2** — rules with *why*  
6. **Q3** — priority aliases → SLA impact  
7. **M1** — session memory recall  

## Soft scoring

Each question has `expect_signals`. Soft-pass = at least half of the signals appear in the response (batch mode). Human judgment still required for DDL/rule quality.
