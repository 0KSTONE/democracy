# council/delivery_vote.py
from dataclasses import dataclass
from typing import Dict, Callable, List, Tuple, Optional
import json
import math
import random
from datetime import date
from pathlib import Path
from bill_tracker import FinanceSnapshot

Score = int  # 0..5
PROMO_RELIABILITY = 0.5  # only count half the advertised promo value to avoid over-reliance

def urgency(shortfall: float, days_remaining: int, daily_need: float, soft: float = 20.0, scale: float = 40.0):
    """
    Adjust urgency based on the shortfall and the time remaining until the next due date.
    Uses daily_need (dollars/day required) as the main pressure signal.
    """
    pressure = max(daily_need, shortfall / max(1, days_remaining))
    x = (pressure - soft) / max(1e-9, scale)
    return 1.0 / (1.0 + math.exp(-x))

# ---------- History tracking ----------
@dataclass
class HistoryEntry:
    date: str       # ISO date string yyyy-mm-dd
    choice: str     # e.g., A_NONE, B_SHORT, C_FULL
    hours: float
    gross: float
    net: float
    actual_hours: Optional[float] = None  # Added field for actual hours worked
    actual_net: Optional[float] = None    # Added field for actual net earnings

@dataclass
class HistoryStats:
    hours_yesterday: float = 0.0
    avg_net_per_hour_recent: float = 0.0

def load_history(path: str = "delivery_history.json", lookback_days: int = 7, max_entries: int = 14) -> List[HistoryEntry]:
    entries: List[HistoryEntry] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    entries.append(HistoryEntry(**obj))
                except Exception:
                    continue
    except FileNotFoundError:
        return []
    # keep only most recent entries (assume file is chronological append)
    entries = entries[-max_entries:]
    # optional: filter by lookback days using date strings
    try:
        today = date.today()
        filtered = []
        for e in reversed(entries):
            d = date.fromisoformat(e.date)
            if (today - d).days <= lookback_days:
                filtered.append(e)
        entries = list(reversed(filtered))
    except Exception:
        pass
    return entries

def summarize_history(entries: List[HistoryEntry]) -> HistoryStats:
    if not entries:
        return HistoryStats()
    # hours yesterday: aggregate by date and take the most recent day
    by_date: Dict[str, float] = {}
    for e in entries:
        by_date[e.date] = by_date.get(e.date, 0.0) + float(e.actual_hours or e.hours)
    most_recent_day = max(by_date.keys())
    hours_yesterday = by_date[most_recent_day]
    # avg net per hour over recent entries with hours > 0
    nets = []
    for e in entries:
        actual_hours = e.actual_hours or e.hours
        actual_net = e.actual_net or e.net
        if actual_hours > 0:
            nets.append(actual_net / actual_hours)
    avg_nph = sum(nets) / len(nets) if nets else 0.0
    return HistoryStats(hours_yesterday=hours_yesterday, avg_net_per_hour_recent=avg_nph)

def append_history_entry(path: str, entry: HistoryEntry):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.__dict__) + "\n")

# ---------- Core voting plumbing ----------
@dataclass
class Agent:
    name: str
    score_fn: Callable[[Dict], Score]
    weight: float = 1.0

@dataclass
class Ballot:
    scores: Dict[str, Score]

def clamp(x, lo=0, hi=5): return max(lo, min(hi, x))

def build_ballot(agent: Agent, options: Dict[str, Dict]) -> Ballot:
    scores = {}
    for cid, opt in options.items():
        s = agent.score_fn(opt)
        s = clamp(int(round(s * agent.weight)))
        scores[cid] = s
    return Ballot(scores)

def star_tally(ballots: List[Ballot]) -> Tuple[str, Dict[str, int]]:
    totals: Dict[str, int] = {}
    for b in ballots:
        for c, s in b.scores.items():
            totals[c] = totals.get(c, 0) + s
    if not totals: return None, {}
    if len(totals) == 1: return next(iter(totals)), totals
    top_two = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    a, b = top_two[0][0], top_two[1][0]
    a_pref = b_pref = 0
    for ballot in ballots:
        sa, sb = ballot.scores.get(a, 0), ballot.scores.get(b, 0)
        if sa > sb: a_pref += 1
        elif sb > sa: b_pref += 1
    if a_pref > b_pref: winner = a
    elif b_pref > a_pref: winner = b
    else:
        if totals[a] > totals[b]: winner = a
        elif totals[b] > totals[a]: winner = b
        else: winner = min(a, b)
    return winner, totals

# ---------- Finance snapshot (fed from bill_tracker) ----------
def build_delivery_options_from_templates(fin: FinanceSnapshot) -> Dict[str, Dict]:
    """Returns three options: NONE, SHORT, FULL with computed economics."""
    templates = {
        "A_NONE":  {"hours": 0.0},
        "B_SHORT": {"hours": min(3.0, fin.hours_available_today)},
        "C_FULL":  {"hours": min(6.0, fin.hours_available_today)},
    }
    # Need gap is pre-computed by the bill tracker; keep wants optional and secondary.
    days_until_due = max(1, fin.next_bill_due_in_days)
    need_gap = max(0.0, fin.bill_shortfall)
    wants_gap = max(0.0, fin.wants_cost - max(0.0, fin.cash_on_hand - fin.bills_due_next_7d))
    daily_need = fin.bill_daily_need

    options: Dict[str, Dict] = {}
    for cid, t in templates.items():
        h = float(t["hours"])
        gross_hr = fin.base_rate_per_hr * fin.tip_multiplier
        gross = gross_hr * h
        miles = fin.miles_per_hr * h
        gas_cost = (miles / max(1e-6, fin.mpg)) * fin.gas_price_per_gal
        maint_cost = 0.15 * miles
        net = gross - gas_cost - maint_cost
        promo_raw = fin.promo_expected_today if fin.promo_available_today else 0.0
        promo_effective = (promo_raw * PROMO_RELIABILITY) if h > 0 else 0.0
        expected_net = net + promo_effective
        gap_covered = min(expected_net, need_gap + 0.5 * wants_gap)  # Wants are weighted less
        options[cid] = {
            "mode": cid, "hours": h,
            "gross": round(gross, 2),
            "gas_cost": round(gas_cost, 2),
            "maint_cost": round(maint_cost, 2),
            "net": round(net, 2),
            "expected_net": round(expected_net, 2),
            "need_gap": round(need_gap, 2),
            "daily_need": round(daily_need, 2),
            "wants_gap": round(wants_gap, 2),
            "gap_covered": round(gap_covered, 2),
            "promo_expected_today": round(promo_raw, 2),
            "promo_effective_today": round(promo_effective, 2),
            "promo_expected_next_days": fin.promo_expected_next_days,
            "energy_required": 2 if h == 0 else (3 if h <= 3 else 4),
            "energy_level": fin.energy_level,
            "est_min": int(h * 60), "setup_min": 10 if h > 0 else 0,
            "past_win_rate": 0.7,
            "recent_fail_rate": 0.2,
            "days_until_due": days_until_due,  # include time pressure for urgency
        }
    return options

# ---------- Agents tuned for delivery choice ----------
def money_agent(history: HistoryStats):
    def _score(o: Dict) -> Score:
        gap = o["need_gap"] + 0.5 * o["wants_gap"]  # Wants are weighted less
        net = o.get("expected_net", o["net"]); h = o["hours"]
        if h == 0:
            return 1 if gap > 0 else 5
        cover = o["gap_covered"]
        cover_ratio = 0.0 if gap <= 0 else min(1.0, cover / gap)
        u = urgency(shortfall=o["need_gap"], days_remaining=o["days_until_due"], daily_need=o.get("daily_need", 0.0))
        # blend expected net/hr with recent actuals if available
        est_eff = net/h if h else 0.0
        eff_hint = history.avg_net_per_hour_recent if history.avg_net_per_hour_recent > 0 else est_eff
        eff = min(1.0, eff_hint/12.0)
        raw = 5.0 * (0.75 * u * cover_ratio + 0.25 * eff)
        return clamp(int(round(raw)))
    return Agent("Money", _score, 1.3)

def rest_prior_agent():
    """
    Gives NONE a soft bonus when gap is small; fades out as urgency rises.
    """
    def _score(o: Dict) -> Score:
        if o["hours"] != 0:
            return 0
        u = urgency(shortfall=o["need_gap"], days_remaining=o["days_until_due"], daily_need=o.get("daily_need", 0.0))
        rest_bonus = 5 * (1.0 - u)
        return clamp(int(round(rest_bonus)))
    return Agent("RestPrior", _score, 1.0)

def energy_agent(history: HistoryStats):
    def _score(o: Dict) -> Score:
        need = o["energy_required"]; have = o["energy_level"]; gap = o["need_gap"]
        if o["hours"] == 0:
            return 5 if gap <= 0 else 3
        effective_have = have
        if history.hours_yesterday >= 6:
            effective_have = max(1, have - 1)
        if need <= effective_have: return 5
        if need == effective_have+1: return 3
        return 1
    return Agent("EnergyMatch", _score, 1.0)

def schedule_agent(hours_available_today: float):
    """
    Blocks choices that don't fit the day.
    """
    def _score(o: Dict) -> Score:
        h = o["hours"]
        if h == 0: return 4
        if h > hours_available_today: return 0
        use_ratio = h / max(0.1, hours_available_today)
        return clamp(int(round(2 + 3*use_ratio)))
    return Agent("ScheduleFit", _score, 1.0)

def safety_agent():
    """
    Penalize if estimated net is negative (gas + maint > gross).
    """
    def _score(o: Dict) -> Score:
        if o["hours"] == 0: return 5
        return 1 if o["net"] <= 0 else 4
    return Agent("Safety", _score, 1.0)

# ---------- Decide ----------
def decide_delivery(fin: FinanceSnapshot, history_path: str = "delivery_history.json"):
    history_file = Path(history_path)
    if not history_file.exists():
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history_file.touch(exist_ok=True)
    options = build_delivery_options_from_templates(fin)
    history_entries = load_history(str(history_file))
    history_stats = summarize_history(history_entries)
    agents = [
        rest_prior_agent(),
        money_agent(history_stats),
        energy_agent(history_stats),
        schedule_agent(fin.hours_available_today),
        safety_agent(),
    ]
    ballots = [build_ballot(a, options) for a in agents]
    winner, totals = star_tally(ballots)

    # soft near-tie nudge toward work when urgency is non-trivial
    sample_opt = next(iter(options.values())) if options else {}
    gap = sample_opt.get("need_gap", 0.0)
    u = urgency(shortfall=gap, days_remaining=sample_opt.get("days_until_due", 7), daily_need=sample_opt.get("daily_need", 0.0))
    if u >= 0.3 and len(totals) >= 2:
        top_two = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
        a, b = top_two[0][0], top_two[1][0]
        def is_work(cid): return options[cid]["hours"] > 0
        near_tie = abs(totals[a] - totals[b]) <= 1
        if near_tie and winner == "A_NONE":
            work_cand = a if is_work(a) else (b if is_work(b) else None)
            if work_cand and random.random() < 0.6:
                winner = work_cand

    # gentle nudge away from NONE toward SHORT when available (slight bias)
    if winner == "A_NONE" and "B_SHORT" in options and options["B_SHORT"]["hours"] > 0:
        nudge_prob = 0.25
        if fin.promo_available_today and options["B_SHORT"]["promo_effective_today"] > 0:
            nudge_prob += 0.2
        if random.random() < nudge_prob:
            winner = "B_SHORT"

    promo_text = (
        f"promo_today=${fin.promo_expected_today:.2f} (avail={fin.promo_available_today}) "
        f"| promo_next_two={list(fin.promo_expected_next_days)}"
    )
    print(
        f"\nFinance: cash ${fin.cash_on_hand:.2f} | bills 7d ${fin.bills_due_next_7d:.2f} "
        f"| shortfall ${fin.bill_shortfall:.2f} | daily_need ${fin.bill_daily_need:.2f}/day "
        f"(next due in {fin.next_bill_due_in_days}d) | {promo_text}"
    )
    print(f"Recent: hours_yesterday={history_stats.hours_yesterday:.1f} | avg_net_per_hr_recent=${history_stats.avg_net_per_hour_recent:.2f}")
    print("Options (computed):")
    for cid, o in options.items():
        print(
            f"  {cid}: hours={o['hours']}, gross=${o['gross']}, gas=${o['gas_cost']}, "
            f"maint=${o['maint_cost']}, net=${o['net']}, exp_net=${o['expected_net']}, "
            f"covers=${o['gap_covered']}, promo_eff=${o['promo_effective_today']}, "
            f"due_in={o['days_until_due']}d"
        )
    for ag, b in zip(agents, ballots):
        print(f"{ag.name} -> {b.scores}")
    print("Totals:", totals)
    print("Winner:", winner, "->", options[winner])

    # Append the decision to the history file
    append_history_entry(str(history_file), HistoryEntry(
        date=str(date.today()),
        choice=winner,
        hours=options[winner]["hours"],
        gross=options[winner]["gross"],
        net=options[winner]["net"],
        actual_hours=options[winner]["hours"],  # Use computed hours as default
        actual_net=options[winner]["net"]       # Use computed net as default
    ))
    return winner, options

# ---------- CLI demo ----------
if __name__ == "__main__":
    from bill_tracker import build_snapshot_from_config
    from decision_logger import log_decision

    # Build the finance snapshot from the central bill_tracker config (includes promos)
    fin = build_snapshot_from_config()

    print(f"Bills due in the next 7 days: ${fin.bills_due_next_7d:.2f}")
    # Run decision and collect data for logging
    winner, options = decide_delivery(fin)

    # Reconstruct agents/ballots for the log to preserve a readable record
    agents_local = [
        rest_prior_agent(),
        money_agent(summarize_history(load_history())),
        energy_agent(summarize_history(load_history())),
        schedule_agent(fin.hours_available_today),
        safety_agent(),
    ]
    ballots_map = {a.name: build_ballot(a, options).scores for a in agents_local}
    totals = {}
    for scores in ballots_map.values():
        for cid, s in scores.items():
            totals[cid] = totals.get(cid, 0) + s

    sample_opt = next(iter(options.values())) if options else {}
    gap = sample_opt.get("need_gap", 0.0)
    extra = {
        "urgency": urgency(shortfall=gap, days_remaining=sample_opt.get("days_until_due", 7), daily_need=sample_opt.get("daily_need", 0.0)),
        "sample_option": sample_opt,
        "totals": totals,
    }

    history_entries = load_history()
    history_stats = summarize_history(history_entries)
    log_decision(fin, options, ballots_map, totals, winner, history_stats, [a.name for a in agents_local], extra=extra)
