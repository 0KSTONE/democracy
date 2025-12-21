import json
from pathlib import Path
from dataclasses import asdict, is_dataclass
from datetime import datetime

LOG_PATH = Path("decision_log.jsonl")

def _to_primitive(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _to_primitive(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_primitive(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)

def log_decision(fin, options, ballots_map, totals, winner, history_stats, agents, extra=None, path=None):
    """
    Append a JSON line with detailed decision data.

    - `fin`: FinanceSnapshot dataclass
    - `options`: dict of computed options
    - `ballots_map`: mapping agent name -> scores dict
    - `totals`: totals per candidate
    - `winner`: winning candidate id
    - `history_stats`: HistoryStats dataclass
    - `agents`: list of agent names or dicts
    - `extra`: optional dict for tie info, urgencies, etc.
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "finance": _to_primitive(fin),
        "history": _to_primitive(history_stats),
        "options": _to_primitive(options),
        "ballots": _to_primitive(ballots_map),
        "totals": _to_primitive(totals),
        "winner": winner,
        "agents": list(agents),
        "extra": _to_primitive(extra) if extra is not None else None,
    }
    p = Path(path) if path else LOG_PATH
    # Write as pretty JSON for readability, separate entries by a blank line
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, indent=2, sort_keys=True))
        f.write("\n\n")

def read_logs(path=None, limit=50):
    """Read up to `limit` entries from the pretty-printed log file.

    Entries are separated by one or more blank lines.
    """
    p = Path(path) if path else LOG_PATH
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    # split on two-or-more newlines
    chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
    out = []
    for chunk in chunks[:limit]:
        try:
            out.append(json.loads(chunk))
        except Exception:
            # skip malformed chunks
            continue
    return out
