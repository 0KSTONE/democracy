Usage (financial decision demo)
- Run with defaults: `python __init__.py --decision financial`
- Adjust hours/energy in code: edit `run_financial_demo` in `__init__.py` or pass your own `FinanceSnapshot` to `decide_delivery`.
- Microtasks (existing flow): `python __init__.py --decision microtask --available-min 25 --energy 3 [--model mymodel:latest --no-ollama]`

Tuning knobs (plain English)
- More NONE wins when money is fine: raise `soft` in `urgency()` (e.g., 80).
- Faster push to work when behind: lower `scale` in `urgency()` (e.g., 90).
- Ties favor work more: raise the 0.6 to 0.7 in the near-tie nudge inside `decide_delivery`.
- FULL wins too often: increase `energy_required` for FULL to 5 or reduce `hours_available_today`.
