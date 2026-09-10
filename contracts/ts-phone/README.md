# TS Phone Protocol Consumer Fixture

The independent `ts-phone` repository owns the Phone API, event, and Bridge
wire contracts. This directory is a byte-for-byte consumer fixture used by
TSPi compatibility tests and package diagnostics; it is not a second authored
protocol source.

Refresh it from an explicit `ts-phone` checkout:

```bash
python3 tools/contracts/sync_ts_phone.py \
  --source /path/to/ts-phone/packages/protocol \
  --write
```

Verify the checked-in fixture and generated Bridge consumer without requiring
the other repository:

```bash
python3 tools/contracts/sync_ts_phone.py --check
```

Pass `--source` with `--check` to also prove byte parity with a particular
`ts-phone` checkout. TSPi owns only the adapter policy in
`extensions/ts-phone-bridge/`; do not edit the generated `protocol.ts`.
