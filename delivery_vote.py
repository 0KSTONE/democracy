# council/delivery_vote.py
from dataclasses import dataclass
from typing import Dict, Callable, List, Tuple, Optional
import json
import math
import random
from datetime import date
from pathlib import Path

Score = int  # 0..5

def urgency(gap, soft=60.0, scale=120.0):
    """
    0.0 when gap is trivial, -> 1.0 as gap gets big.
    soft: where the curve starts biting; scale: how fast it ramps.
    """
    x = (gap - soft) / max(1e-9, scale)
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
        by_date[e.date] = by_date.get(e.date, 0.0) + float(e.hours)
    most_recent_day = max(by_date.keys())
    hours_yesterday = by_date[most_recent_day]
    # avg net per hour over recent entries with hours>0
    nets = []
    for e in entries:
        if e.hours > 0:
            nets.append(e.net / e.hours)
    avg_nph = sum(nets)/len(nets) if nets else 0.0
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

# ---------- Finance snapshot (manual, no bank link) ----------
@dataclass
class FinanceSnapshot:
    cash_on_hand: float              # e.g., 64.00
    bills_due_next_7d: float         # e.g., 420.00 (phone+insurance)
    gas_price_per_gal: float         # e.g., 3.60
    mpg: float                       # your car's miles per gallon
    base_rate_per_hr: float          # conservative $/hr estimate (base pay only)
    tip_multiplier: float            # 1.0 = no tips; 1.3 = +30%
    miles_per_hr: float              # avg miles driven per working hour
    energy_level: int                # 1..5 honest energy
    hours_available_today: float     # max hours you can work today
    wants_cost: float        # Optional cost for wants (e.g., $50 for leisure)

def build_delivery_options_from_templates(fin: FinanceSnapshot) -> Dict[str, Dict]:
    """
    Returns three options: NONE, SHORT, FULL with computed economics.
    You can change durations or add more modes without touching agents.
    """
    templates = {
        "A_NONE":  {"hours": 0.0},
        "B_SHORT": {"hours": min(3.0, fin.hours_available_today)},
        "C_FULL":  {"hours": min(6.0, fin.hours_available_today)},
    }
    # Step 2: Incorporate "wants" cost into the delivery options computation
    need_gap = max(0.0, fin.bills_due_next_7d - fin.cash_on_hand)  # dollars needed this week
    wants_gap = max(0.0, fin.wants_cost - max(0.0, fin.cash_on_hand - fin.bills_due_next_7d))

    options: Dict[str, Dict] = {}
    for cid, t in templates.items():
        h = float(t["hours"])
        gross_hr = fin.base_rate_per_hr * fin.tip_multiplier
        gross = gross_hr * h
        miles = fin.miles_per_hr * h
        gas_cost = (miles / max(1e-6, fin.mpg)) * fin.gas_price_per_gal
        maint_cost = 0.15 * miles
        net = gross - gas_cost - maint_cost
        gap_covered = min(net, need_gap + 0.5 * wants_gap)  # Wants are weighted less
        options[cid] = {
            "mode": cid, "hours": h,
            "gross": round(gross, 2),
            "gas_cost": round(gas_cost, 2),
            "maint_cost": round(maint_cost, 2),
            "net": round(net, 2),
            "need_gap": round(need_gap, 2),
            "wants_gap": round(wants_gap, 2),
            "gap_covered": round(gap_covered, 2),
            "energy_required": 2 if h==0 else (3 if h<=3 else 4),
            "energy_level": fin.energy_level,
            "est_min": int(h*60), "setup_min": 10 if h>0 else 0,
            "past_win_rate": 0.7,
            "recent_fail_rate": 0.2,
        }
    return options

# ---------- Agents tuned for delivery choice ----------
def money_agent(history: HistoryStats):
    def _score(o: Dict) -> Score:
        gap = o["need_gap"] + 0.5 * o["wants_gap"]  # Wants are weighted less
        net = o["net"]; h = o["hours"]
        if h == 0:
            return 1 if gap > 0 else 5
        cover = o["gap_covered"]
        cover_ratio = 0.0 if gap <= 0 else min(1.0, cover / gap)
        u = urgency(gap, soft=60, scale=120)
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
        u = urgency(o["need_gap"], soft=60, scale=120)
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
    gap = list(options.values())[0]["need_gap"] if options else 0.0
    u = urgency(gap, soft=60, scale=120)
    if u >= 0.3 and len(totals) >= 2:
        top_two = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
        a, b = top_two[0][0], top_two[1][0]
        def is_work(cid): return options[cid]["hours"] > 0
        near_tie = abs(totals[a] - totals[b]) <= 1
        if near_tie and winner == "A_NONE":
            work_cand = a if is_work(a) else (b if is_work(b) else None)
            if work_cand and random.random() < 0.6:
                winner = work_cand

    print(f"\nFinance: cash ${fin.cash_on_hand:.2f} | bills 7d ${fin.bills_due_next_7d:.2f} | need_gap ${max(0, fin.bills_due_next_7d-fin.cash_on_hand):.2f}")
    print(f"Recent: hours_yesterday={history_stats.hours_yesterday:.1f} | avg_net_per_hr_recent=${history_stats.avg_net_per_hour_recent:.2f}")
    print("Options (computed):")
    for cid, o in options.items():
        print(f"  {cid}: hours={o['hours']}, gross=${o['gross']}, gas=${o['gas_cost']}, maint=${o['maint_cost']}, net=${o['net']}, covers=${o['gap_covered']}")
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
    fin = FinanceSnapshot(
        cash_on_hand=120.0,
        bills_due_next_7d=420.0,
        gas_price_per_gal=3.60,
        mpg=15.0,
        base_rate_per_hr=12.0,
        tip_multiplier=1.3,
        miles_per_hr=12.0,
        energy_level=3,
        hours_available_today=6.0,
        wants_cost=165.0,
    )
    decide_delivery(fin)
