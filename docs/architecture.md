# Architecture

```mermaid
flowchart TD
    CSV[("input CSV<br/>spotify_reviews_18months.csv<br/>660,622 rows")]

    subgraph S1["1 · Prepare — code only (pipeline/ingest.py)"]
        I1["parse every row (multiline-safe)<br/>row_sha = checker hash · profile · find exact duplicate texts"]
        I2["quarantine 13 empty texts<br/>queue 484,189 distinct texts as pending"]
    end

    subgraph S2["2 · Classify — role: enrich (pipeline/enrich.py)"]
        E0{"code: cache hit for<br/>text + label_config?"}
        E1["build request ≤ 50 reviews<br/>reserve worst-case $ in shared ledger"]
        E2(["MODEL gpt-6-luna, effort=none<br/>prompt enrich_v1 · strict JSON schema"])
        E3{"code: validate every ID, enum,<br/>range, quote ⊂ source"}
        E4["retry invalid subset once<br/>transient 429/5xx: bounded backoff"]
        E5["atomic SQLite commit per batch<br/>original + exact-text aliases (cache_source_id)"]
        EQ["quarantine with reason + attempts"]
    end

    subgraph S3["3 · Verify — role: verify (pipeline/verify.py)"]
        V1["seeded random sample of sent originals"]
        V2(["MODEL gemma4:e4b (local Ollama)<br/>prompt verify_v1 · sees text only"])
        V3["code: compare · disagreement report · planted-error test"]
    end

    subgraph S4["4 · Group — role: group (pipeline/group.py)"]
        G1["code: membership = topic.subtopic<br/>one issue per complaint/cancellation"]
        G2(["MODEL gpt-6-luna: names issues from a<br/>bounded evidence pack (≤ 6 quotes/issue)"])
    end

    subgraph S5["5 · Rank — code only (pipeline/rank.py)"]
        R1["priority = complaint_count × mean_severity = severity_sum<br/>sort desc score, asc issue_id · reads only saved files"]
    end

    subgraph S6["6 · Recommend — role: memo (pipeline/memo.py)"]
        M0["code: aggregates + claims.csv (C/A/T/K claim IDs)"]
        M1(["MODEL gpt-6-luna, effort=low<br/>prompt memo_v1 · evidence pack only"])
        M2{"code: every number ↔ claim value,<br/>every issue/review ID ∈ pack"}
    end

    subgraph OUT["Saved artifacts (inspectable handoffs)"]
        O1["records.jsonl.gz · quarantine.jsonl · calls.jsonl · run_log.jsonl"]
        O2["membership.csv · ranking.csv · aggregates.json"]
        O3["memo.md · claims.csv · grading/ · cost/"]
    end

    subgraph WEB["Deployed"]
        DB[("Neon Postgres<br/>reviews · issues · claims · memo · meta")]
        API["Vercel serverless API<br/>/api/overview /ranking /issue /memo /review"]
        UI["Dashboard<br/>metrics · ranking · AI recommendation · trace"]
    end

    CSV --> I1 --> I2 --> E0
    E0 -- hit --> E5
    E0 -- miss --> E1 --> E2 --> E3
    E3 -- valid --> E5
    E3 -- invalid --> E4 --> E2
    E4 -- "still invalid" --> EQ
    E5 --> V1 --> V2 --> V3
    E5 --> G1 --> G2 --> R1 --> M0 --> M1 --> M2
    M2 -- "problems: one retry with feedback" --> M1
    E5 --> O1
    R1 --> O2
    M2 --> O3
    O1 & O2 & O3 -->|dashboard/load_db.py| DB --> API --> UI
```

**Where code decides vs where a model judges**

| Step | Code (deterministic) | Model (language judgment) |
|---|---|---|
| Prepare | parsing, hashing, profiling, dedup, empty-text quarantine, queue | — |
| Classify | batching ≤ 50, budget reservation, ID/enum/range validation, quote membership, entity extraction (fixed term list), retries, cache reuse, statuses | topic.subtopic, intent, severity, sentiment, evidence span, needs_review |
| Verify | seeded sampling, comparison, planted errors | independent blind re-label (different model family) |
| Group | membership (topic.subtopic), evidence-pack selection, ID validation | short issue names/descriptions; flag off-topic examples |
| Rank | all arithmetic, tie-break | — |
| Recommend | aggregates, claims, number/ID checks, retry | weigh alternatives and write the argument |

**Stop / retry rules.** Enrich: invalid output → one retry of the failing subset, then quarantine with reason; transient errors →
≤ 4 backoff retries with jitter; 5 consecutive failed batches → stop; spend cap: refuse dispatch when spent + reserved + next
reservation > cap; Ctrl+C → finish in-flight batches, commit, snapshot, exit. Memo: one retry with the failed checks listed,
then save with `check.passed=false` (never silently).
