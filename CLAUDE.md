# meeseeks-core

Python 3.11, src layout, venv at `.venv`. Always use `.venv/bin/python` and `.venv/bin/pytest`.
Repo: `/root/meeseeks-core/`

## Key rules
- Never use `multiprocessing.fork` — always `spawn` start method (§3.2)
- All IPC via `multiprocessing.Queue` or `multiprocessing.Pipe`, never shared memory
- Subprocess worker functions must be **module-level** (not nested/lambda) — pickle requires it
- Test with `.venv/bin/pytest`, not `python -m pytest`
- After each change run: `.venv/bin/pytest tests/test_contracts.py tests/test_registry.py tests/test_public_api.py -q`
