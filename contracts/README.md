# Contracts

- `observatory_metrics_item.json`, `conformance.py` — the `OBSERVATORY_METRICS`
  item contract. **Canonical here**; vendored into every writer and reader.
- `score_envelope.json`, `score_contract.py` — what a score in `[0, 1]` means
  across the weave systems and which may be combined. **Vendored** byte-identical
  from [`ContextWeave/contracts/`](https://github.com/rajatarun/ContextWeave/tree/main/contracts);
  `tests/test_score_contract.py` pins their sha256. Do not edit them here.
- `scores.json` — mcp-observatory's own declaration of the scores it emits.
