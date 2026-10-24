"""
analysis/export_html_dashboard.py
Generates a standalone HTML executive summary dashboard of market statistics,
covering the trailing 30-day window: FII/DII activity, sector leadership,
dominant event category, prediction hit-rate, market structure, global-cue
correlation, learnings digest and macro context.
"""

import sqlite3
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "market.db"
REPORT_PATH = BASE_DIR / "reports" / "dashboard.html"

WINDOW_DAYS = 30


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def pearson(xs, ys):
    """Simple Pearson correlation for two equal-length numeric lists."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 3:
        return None
    xs, ys = zip(*pairs)
    mx, my = mean(xs), mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def fmt_cr(val):
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:,.0f} cr"


def cls_for(val):
    if val is None:
        return ""
    return "pos" if val >= 0 else "neg"


def window_bounds(conn):
    max_date = conn.execute("SELECT MAX(date) FROM daily_data;").fetchone()[0]
    max_dt = datetime.strptime(max_date, "%Y-%m-%d")
    start_dt = max_dt - timedelta(days=WINDOW_DAYS)
    return start_dt.strftime("%Y-%m-%d"), max_date


# ----------------------------------------------------------------------
# 1. FII / DII activity
# ----------------------------------------------------------------------

def fii_dii_summary(conn, start_date, end_date):
    rows = conn.execute(
        """SELECT date, fii_equity_cr, dii_equity_cr FROM daily_data
           WHERE date BETWEEN ? AND ? ORDER BY date ASC;""",
        (start_date, end_date),
    ).fetchall()

    fii_vals = [(d, f) for d, f, _ in rows if f is not None]
    dii_vals = [(d, di) for d, _, di in rows if di is not None]

    net_fii = sum(v for _, v in fii_vals)
    net_dii = sum(v for _, v in dii_vals)

    fii_buy_days = sum(1 for _, v in fii_vals if v > 0)
    fii_sell_days = sum(1 for _, v in fii_vals if v < 0)
    dii_buy_days = sum(1 for _, v in dii_vals if v > 0)
    dii_sell_days = sum(1 for _, v in dii_vals if v < 0)

    max_inflow = max(fii_vals, key=lambda x: x[1], default=(None, None))
    max_outflow = min(fii_vals, key=lambda x: x[1], default=(None, None))

    fii_by_date = {d: v for d, v in fii_vals}
    dii_by_date = {d: v for d, v in dii_vals}
    divergence_days = [
        d for d in fii_by_date
        if d in dii_by_date and fii_by_date[d] * dii_by_date[d] < 0
    ]

    verdict = (
        f"FII net {'buyer' if net_fii >= 0 else 'seller'} of {fmt_cr(net_fii)} "
        f"over the window; DII net {'buyer' if net_dii >= 0 else 'seller'} of "
        f"{fmt_cr(net_dii)} — "
        f"{'DII offset FII outflows' if net_fii < 0 and net_dii > 0 else 'both aligned' if net_fii * net_dii >= 0 else 'mixed positioning'}."
    )

    return {
        "n_days": len(rows),
        "net_fii": net_fii,
        "net_dii": net_dii,
        "fii_buy_days": fii_buy_days,
        "fii_sell_days": fii_sell_days,
        "dii_buy_days": dii_buy_days,
        "dii_sell_days": dii_sell_days,
        "max_inflow": max_inflow,
        "max_outflow": max_outflow,
        "divergence_days": len(divergence_days),
        "verdict": verdict,
    }


# ----------------------------------------------------------------------
# 2. Sector performance
# ----------------------------------------------------------------------

def sector_performance(conn, start_date, end_date):
    rows = conn.execute(
        """SELECT date, sector_name, performance, sector_return_pct FROM sectors
           WHERE date BETWEEN ? AND ? ORDER BY date ASC;""",
        (start_date, end_date),
    ).fetchall()

    stats = {}
    for date, name, perf, pct in rows:
        s = stats.setdefault(name, {"gainer": 0, "loser": 0, "returns": []})
        if perf == "TOP_GAINER":
            s["gainer"] += 1
        elif perf == "TOP_LOSER":
            s["loser"] += 1
        if pct is not None:
            try:
                s["returns"].append(float(pct))
            except ValueError:
                pass

    ranking = []
    for name, s in stats.items():
        avg_ret = mean(s["returns"]) if s["returns"] else None
        ranking.append({
            "sector": name,
            "gainer_days": s["gainer"],
            "loser_days": s["loser"],
            "avg_return": avg_ret,
            "appearances": s["gainer"] + s["loser"],
        })

    with_returns = [r for r in ranking if r["avg_return"] is not None]
    best = max(with_returns, key=lambda r: r["avg_return"], default=None)
    worst = min(with_returns, key=lambda r: r["avg_return"], default=None)
    most_volatile = max(
        [r for r in ranking if r["gainer_days"] > 0 and r["loser_days"] > 0],
        key=lambda r: r["appearances"],
        default=None,
    )
    ranking.sort(key=lambda r: (r["avg_return"] is None, -(r["avg_return"] or 0)))

    return {
        "n_logged": len(rows),
        "ranking": ranking,
        "best": best,
        "worst": worst,
        "most_volatile": most_volatile,
    }


# ----------------------------------------------------------------------
# 3. Dominant event category
# ----------------------------------------------------------------------

def event_category_summary(conn, start_date, end_date):
    rows = conn.execute(
        """SELECT event_category, event_type, impact_direction, impact_magnitude,
                  event_description, date FROM events
           WHERE date BETWEEN ? AND ? ORDER BY date ASC;""",
        (start_date, end_date),
    ).fetchall()

    cats = {}
    type_counts = {"GLOBAL": 0, "DOMESTIC": 0}
    for cat, etype, direction, mag, desc, date in rows:
        c = cats.setdefault(cat, {"count": 0, "weight": 0, "bullish": 0, "bearish": 0})
        c["count"] += 1
        c["weight"] += mag or 0
        if direction == "BULLISH":
            c["bullish"] += 1
        elif direction == "BEARISH":
            c["bearish"] += 1
        if etype in type_counts:
            type_counts[etype] += 1

    dominant = max(cats.items(), key=lambda kv: kv[1]["weight"], default=(None, None))
    top_event = max(rows, key=lambda r: (r[3] or 0), default=None)

    return {
        "n_events": len(rows),
        "by_category": cats,
        "dominant_category": dominant[0],
        "dominant_weight": dominant[1]["weight"] if dominant[1] else None,
        "type_counts": type_counts,
        "top_event": top_event,
    }


# ----------------------------------------------------------------------
# 4. Prediction hit-rate analysis
# ----------------------------------------------------------------------

def prediction_hit_analysis(conn, start_date, end_date):
    rows = conn.execute(
        """SELECT date, tomorrow_bias, emotional_state, prediction_hit
           FROM daily_data WHERE date BETWEEN ? AND ?
           AND prediction_hit IS NOT NULL ORDER BY date ASC;""",
        (start_date, end_date),
    ).fetchall()

    n = len(rows)
    overall = (sum(r[3] for r in rows) / n * 100) if n else None

    def rate_by(idx):
        buckets = {}
        for r in rows:
            key = r[idx] or "UNLOGGED"
            b = buckets.setdefault(key, {"hits": 0, "n": 0})
            b["hits"] += r[3]
            b["n"] += 1
        return {
            k: {"hit_rate": v["hits"] / v["n"] * 100, "n": v["n"]}
            for k, v in buckets.items()
        }

    by_bias = rate_by(1)
    by_emotion = rate_by(2)

    half = n // 2
    first_half = rows[:half]
    second_half = rows[half:]
    first_rate = (sum(r[3] for r in first_half) / len(first_half) * 100) if first_half else None
    second_rate = (sum(r[3] for r in second_half) / len(second_half) * 100) if second_half else None

    return {
        "n": n,
        "overall_hit_rate": overall,
        "by_bias": by_bias,
        "by_emotion": by_emotion,
        "first_half_rate": first_rate,
        "second_half_rate": second_rate,
    }


# ----------------------------------------------------------------------
# 5. Market structure / trend
# ----------------------------------------------------------------------

def market_structure_summary(conn, start_date, end_date):
    rows = conn.execute(
        """SELECT date, nifty_close, nifty_high, nifty_low, nifty_change_pct,
                  vix_close, vix_change_pct, pcr_value, advance_decline_ratio,
                  resistance_imm, support_imm
           FROM daily_data WHERE date BETWEEN ? AND ? ORDER BY date ASC;""",
        (start_date, end_date),
    ).fetchall()

    if not rows:
        return None

    month_open = rows[0][1]
    month_close = rows[-1][1]
    pct_return = ((month_close - month_open) / month_open * 100) if month_open else None
    highs = [r[2] for r in rows if r[2] is not None]
    lows = [r[3] for r in rows if r[3] is not None]
    up_days = sum(1 for r in rows if r[4] is not None and r[4] > 0)
    down_days = sum(1 for r in rows if r[4] is not None and r[4] < 0)

    vix_vals = [r[5] for r in rows if r[5] is not None]
    vix_avg = mean(vix_vals) if vix_vals else None
    vix_trend = (vix_vals[-1] - vix_vals[0]) if len(vix_vals) >= 2 else None

    nifty_chg = [r[4] for r in rows]
    vix_chg = [r[6] for r in rows]
    corr_nifty_vix = pearson(nifty_chg, vix_chg)

    pcr_vals = [r[7] for r in rows if r[7] is not None]
    adr_vals = [r[8] for r in rows if r[8] is not None]

    breakout_up = sum(1 for r in rows if r[1] and r[9] and r[1] > r[9])
    breakout_down = sum(1 for r in rows if r[1] and r[10] and r[1] < r[10])

    return {
        "n_days": len(rows),
        "month_open": month_open,
        "month_close": month_close,
        "pct_return": pct_return,
        "high": max(highs) if highs else None,
        "low": min(lows) if lows else None,
        "up_days": up_days,
        "down_days": down_days,
        "vix_avg": vix_avg,
        "vix_trend": vix_trend,
        "corr_nifty_vix": corr_nifty_vix,
        "pcr_avg": mean(pcr_vals) if pcr_vals else None,
        "adr_avg": mean(adr_vals) if adr_vals else None,
        "breakout_up_days": breakout_up,
        "breakout_down_days": breakout_down,
    }


# ----------------------------------------------------------------------
# 6. Global cues correlation
# ----------------------------------------------------------------------

def global_cues_correlation(conn, start_date, end_date):
    vibe_rows = conn.execute(
        """SELECT date, gift_nifty_pct, market_vibe_label, confidence_score,
                  us_sp500_pct, us_nasdaq_pct
           FROM market_vibe WHERE date BETWEEN ? AND ? ORDER BY date ASC;""",
        (start_date, end_date),
    ).fetchall()

    daily_rows = conn.execute(
        """SELECT date, nifty_change_pct FROM daily_data
           WHERE date BETWEEN ? AND ? ORDER BY date ASC;""",
        (start_date, end_date),
    ).fetchall()
    nifty_by_date = [(d, c) for d, c in daily_rows]

    def next_day_change(vibe_date):
        for d, c in nifty_by_date:
            if d > vibe_date:
                return c
        return None

    gift_vals, next_change_vals = [], []
    label_counts = {}
    confidences = []
    for date, gift_pct, label, conf, sp500, nasdaq in vibe_rows:
        nxt = next_day_change(date)
        if gift_pct is not None and nxt is not None:
            gift_vals.append(gift_pct)
            next_change_vals.append(nxt)
        if label:
            label_counts[label] = label_counts.get(label, 0) + 1
        if conf is not None:
            confidences.append(conf)

    corr = pearson(gift_vals, next_change_vals)

    return {
        "n": len(vibe_rows),
        "corr_gift_vs_next_day": corr,
        "label_counts": label_counts,
        "avg_confidence": mean(confidences) if confidences else None,
        "pairs_used": len(gift_vals),
    }


# ----------------------------------------------------------------------
# 7. Learnings digest
# ----------------------------------------------------------------------

def learnings_digest(conn, start_date, end_date):
    rows = conn.execute(
        """SELECT date, lesson_priority, lesson_text, lesson_category, actionable
           FROM learnings WHERE date BETWEEN ? AND ? AND actionable = 1
           ORDER BY lesson_priority DESC, date DESC;""",
        (start_date, end_date),
    ).fetchall()

    by_category = {}
    for date, priority, text, category, actionable in rows:
        by_category[category] = by_category.get(category, 0) + 1

    top_items = rows[:5]

    return {
        "n_actionable": len(rows),
        "by_category": by_category,
        "top_items": top_items,
    }


# ----------------------------------------------------------------------
# 8. Macro context
# ----------------------------------------------------------------------

def macro_context(conn, start_date, end_date):
    rows = conn.execute(
        """SELECT date, brent_crude, usd_inr, fii_equity_cr FROM daily_data
           WHERE date BETWEEN ? AND ? ORDER BY date ASC;""",
        (start_date, end_date),
    ).fetchall()

    brent_vals = [(d, b) for d, b, _, _ in rows if b is not None]
    inr_vals = [(d, u) for d, _, u, _ in rows if u is not None]

    brent_change = None
    if len(brent_vals) >= 2:
        brent_change = (brent_vals[-1][1] - brent_vals[0][1]) / brent_vals[0][1] * 100
    inr_change = None
    if len(inr_vals) >= 2:
        inr_change = (inr_vals[-1][1] - inr_vals[0][1]) / inr_vals[0][1] * 100

    # cross-reference: days with >2% single-day brent move (day over day) and FII outflow
    flagged = []
    prev_brent = None
    for date, brent, inr, fii in rows:
        if brent is not None and prev_brent is not None and prev_brent != 0:
            day_chg = (brent - prev_brent) / prev_brent * 100
            if abs(day_chg) >= 2 and fii is not None and fii < 0:
                flagged.append((date, round(day_chg, 2), fii))
        if brent is not None:
            prev_brent = brent

    return {
        "brent_start": brent_vals[0][1] if brent_vals else None,
        "brent_end": brent_vals[-1][1] if brent_vals else None,
        "brent_change_pct": brent_change,
        "inr_start": inr_vals[0][1] if inr_vals else None,
        "inr_end": inr_vals[-1][1] if inr_vals else None,
        "inr_change_pct": inr_change,
        "flagged_days": flagged,
    }


# ----------------------------------------------------------------------
# HTML rendering
# ----------------------------------------------------------------------

def render_dashboard(counts, snapshot, fii_dii, sector, events, prediction,
                      structure, global_cues, learnings, macro,
                      start_date, end_date):

    def metric(label, value, css=""):
        return f'<div class="metric"><div>{label}</div><div class="metric-val {css}">{value}</div></div>'

    # --- FII/DII card ---
    fii_dii_html = f"""
    <div class="card">
      <h2>FII / DII Activity — Last 30 Days ({fii_dii['n_days']} trading days, {start_date} to {end_date})</h2>
      <div class="metric-grid">
        {metric('Net FII (Equity)', fmt_cr(fii_dii['net_fii']), cls_for(fii_dii['net_fii']))}
        {metric('Net DII (Equity)', fmt_cr(fii_dii['net_dii']), cls_for(fii_dii['net_dii']))}
        {metric('FII Buy / Sell Days', f"{fii_dii['fii_buy_days']} / {fii_dii['fii_sell_days']}")}
        {metric('DII Buy / Sell Days', f"{fii_dii['dii_buy_days']} / {fii_dii['dii_sell_days']}")}
      </div>
      <ul>
        <li><b>Largest FII inflow:</b> {fii_dii['max_inflow'][0]} ({fmt_cr(fii_dii['max_inflow'][1])})</li>
        <li><b>Largest FII outflow:</b> {fii_dii['max_outflow'][0]} ({fmt_cr(fii_dii['max_outflow'][1])})</li>
        <li><b>FII/DII divergence days:</b> {fii_dii['divergence_days']}</li>
      </ul>
      <p class="verdict">{fii_dii['verdict']}</p>
    </div>
    """

    # --- Sector card ---
    rows_html = ""
    for r in sector["ranking"][:8]:
        ret = f"{r['avg_return']:.2f}%" if r["avg_return"] is not None else "N/A"
        rows_html += (
            f"<tr><td>{r['sector']}</td><td>{r['gainer_days']}</td>"
            f"<td>{r['loser_days']}</td><td>{ret}</td></tr>"
        )
    best = sector["best"]
    worst = sector["worst"]
    vol = sector["most_volatile"]
    sector_html = f"""
    <div class="card">
      <h2>Sector Leadership — Last 30 Days ({sector['n_logged']} logged entries, {start_date} to {end_date})</h2>
      <p><b>Top performer:</b> {best['sector'] if best else 'N/A'}
         ({f"{best['avg_return']:.2f}% avg" if best and best['avg_return'] is not None else 'N/A'})
         &nbsp;|&nbsp; <b>Weakest:</b> {worst['sector'] if worst else 'N/A'}
         ({f"{worst['avg_return']:.2f}% avg" if worst and worst['avg_return'] is not None else 'N/A'})
         &nbsp;|&nbsp; <b>Most volatile:</b> {vol['sector'] if vol else 'N/A'}</p>
      <table>
        <tr><th>Sector</th><th>Gainer days</th><th>Loser days</th><th>Avg return</th></tr>
        {rows_html}
      </table>
    </div>
    """

    # --- Events card ---
    cat_rows = ""
    for cat, c in sorted(events["by_category"].items(), key=lambda kv: -kv[1]["weight"]):
        cat_rows += (
            f"<tr><td>{cat}</td><td>{c['count']}</td><td>{c['weight']}</td>"
            f"<td>{c['bullish']} / {c['bearish']}</td></tr>"
        )
    top_evt = events["top_event"]
    events_html = f"""
    <div class="card">
      <h2>Event Landscape — Last 30 Days ({events['n_events']} events, {start_date} to {end_date})</h2>
      <div class="metric-grid">
        {metric('Dominant Category', events['dominant_category'] or 'N/A')}
        {metric('Global Events', events['type_counts']['GLOBAL'])}
        {metric('Domestic Events', events['type_counts']['DOMESTIC'])}
      </div>
      <table>
        <tr><th>Category</th><th>Count</th><th>Impact weight</th><th>Bullish / Bearish</th></tr>
        {cat_rows}
      </table>
      <p><b>Highest-magnitude event:</b> {top_evt[5] if top_evt else 'N/A'} —
      "{top_evt[4].strip() if top_evt else ''}" (magnitude {top_evt[3] if top_evt else 'N/A'})</p>
    </div>
    """

    # --- Prediction hit-rate card ---
    bias_rows = "".join(
        f"<tr><td>{k}</td><td>{v['n']}</td><td>{v['hit_rate']:.1f}%</td></tr>"
        for k, v in prediction["by_bias"].items()
    )
    emo_rows = "".join(
        f"<tr><td>{k}</td><td>{v['n']}</td><td>{v['hit_rate']:.1f}%</td></tr>"
        for k, v in prediction["by_emotion"].items()
    )
    fh = prediction["first_half_rate"]
    sh = prediction["second_half_rate"]
    trend = "improving" if (fh is not None and sh is not None and sh > fh) else "declining" if (fh is not None and sh is not None and sh < fh) else "flat"
    prediction_html = f"""
    <div class="card">
      <h2>Prediction Hit-Rate — Last 30 Days ({prediction['n']} logged predictions, {start_date} to {end_date})</h2>
      <div class="metric-grid">
        {metric('Overall Hit Rate', f"{prediction['overall_hit_rate']:.1f}%" if prediction['overall_hit_rate'] is not None else 'N/A')}
        {metric('1st Half of Window', f"{fh:.1f}%" if fh is not None else 'N/A')}
        {metric('2nd Half of Window', f"{sh:.1f}%" if sh is not None else 'N/A')}
        {metric('Trend', trend.capitalize())}
      </div>
      <div class="metric-grid">
        <div style="flex:1"><h3>By predicted bias</h3><table><tr><th>Bias</th><th>N</th><th>Hit rate</th></tr>{bias_rows}</table></div>
        <div style="flex:1"><h3>By emotional state</h3><table><tr><th>State</th><th>N</th><th>Hit rate</th></tr>{emo_rows}</table></div>
      </div>
    </div>
    """

    # --- Market structure card ---
    s = structure
    structure_html = f"""
    <div class="card">
      <h2>Market Structure — Last 30 Days ({s['n_days']} trading days, {start_date} to {end_date})</h2>
      <div class="metric-grid">
        {metric('Nifty Return', f"{s['pct_return']:.2f}%" if s['pct_return'] is not None else 'N/A', cls_for(s['pct_return']))}
        {metric('Range (High / Low)', f"{s['high']:.0f} / {s['low']:.0f}" if s['high'] else 'N/A')}
        {metric('Up / Down Days', f"{s['up_days']} / {s['down_days']}")}
        {metric('Avg VIX', f"{s['vix_avg']:.2f}" if s['vix_avg'] is not None else 'N/A')}
      </div>
      <ul>
        <li><b>VIX change over window:</b> {f"{s['vix_trend']:+.2f} pts" if s['vix_trend'] is not None else 'N/A'}</li>
        <li><b>Nifty–VIX daily correlation:</b> {f"{s['corr_nifty_vix']:.2f}" if s['corr_nifty_vix'] is not None else 'N/A'}</li>
        <li><b>Avg PCR:</b> {f"{s['pcr_avg']:.2f}" if s['pcr_avg'] is not None else 'N/A'}
            &nbsp;|&nbsp; <b>Avg Advance/Decline ratio:</b> {f"{s['adr_avg']:.2f}" if s['adr_avg'] is not None else 'N/A'}</li>
        <li><b>Closed above immediate resistance:</b> {s['breakout_up_days']} days
            &nbsp;|&nbsp; <b>Closed below immediate support:</b> {s['breakout_down_days']} days</li>
      </ul>
    </div>
    """

    # --- Global cues card ---
    label_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in global_cues["label_counts"].items())
    gc = global_cues
    global_html = f"""
    <div class="card">
      <h2>Global Cues — Last 30 Days ({gc['n']} logged days, {start_date} to {end_date})</h2>
      <div class="metric-grid">
        {metric('GIFT Nifty → Next-Day Corr.', f"{gc['corr_gift_vs_next_day']:.2f}" if gc['corr_gift_vs_next_day'] is not None else 'N/A')}
        {metric('Avg Confidence Score', f"{gc['avg_confidence']:.1f}" if gc['avg_confidence'] is not None else 'N/A')}
        {metric('Pairs Used', gc['pairs_used'])}
      </div>
      <table><tr><th>Market vibe label</th><th>Days</th></tr>{label_rows}</table>
    </div>
    """

    # --- Learnings card ---
    lc = learnings
    cat_list = "".join(f"<li>{k}: {v}</li>" for k, v in lc["by_category"].items())
    items = "".join(
        f"<li><b>[{cat}, P{pri}]</b> {text.strip()} <span class='faint'>({date})</span></li>"
        for date, pri, text, cat, act in lc["top_items"]
    )
    learnings_html = f"""
    <div class="card">
      <h2>Learnings Digest — Last 30 Days ({lc['n_actionable']} actionable entries, {start_date} to {end_date})</h2>
      <p><b>By category:</b></p>
      <ul>{cat_list}</ul>
      <p><b>Top-priority takeaways:</b></p>
      <ul>{items}</ul>
    </div>
    """

    # --- Macro card ---
    m = macro
    flagged_html = "".join(
        f"<li>{d}: Brent moved {chg:+.2f}% while FII sold {fmt_cr(fii)}</li>"
        for d, chg, fii in m["flagged_days"]
    ) or "<li>None this window.</li>"
    macro_html = f"""
    <div class="card">
      <h2>Macro Context — Last 30 Days ({start_date} to {end_date})</h2>
      <div class="metric-grid">
        {metric('Brent Crude', f"{m['brent_start']:.1f} → {m['brent_end']:.1f}" if m['brent_start'] else 'N/A')}
        {metric('Brent Change', f"{m['brent_change_pct']:+.2f}%" if m['brent_change_pct'] is not None else 'N/A', cls_for(m['brent_change_pct']))}
        {metric('USD/INR', f"{m['inr_start']:.2f} → {m['inr_end']:.2f}" if m['inr_start'] else 'N/A')}
        {metric('USD/INR Change', f"{m['inr_change_pct']:+.2f}%" if m['inr_change_pct'] is not None else 'N/A')}
      </div>
      <p><b>Sharp Brent moves coinciding with FII selling:</b></p>
      <ul>{flagged_html}</ul>
    </div>
    """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Market Database Executive Summary</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 30px; background: #f8f9fa; color: #212529; }}
            .card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
            h1 {{ color: #0d6efd; border-bottom: 2px solid #0d6efd; padding-bottom: 10px; }}
            h2 {{ margin-top: 0; }}
            h3 {{ margin-bottom: 6px; }}
            .metric-grid {{ display: flex; gap: 20px; text-align: center; flex-wrap: wrap; margin-bottom: 12px; }}
            .metric {{ flex: 1; min-width: 140px; padding: 15px; background: #e9ecef; border-radius: 6px; }}
            .metric-val {{ font-size: 22px; font-weight: bold; color: #198754; }}
            .metric-val.neg {{ color: #dc3545; }}
            .metric-val.pos {{ color: #198754; }}
            .dd-neg {{ color: #dc3545; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
            th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #e9ecef; font-size: 14px; }}
            .verdict {{ font-style: italic; color: #495057; }}
            .scope-note {{ font-size: 13px; color: #495057; background: #fff3cd; padding: 8px 12px; border-radius: 6px; border-left: 3px solid #ffc107; }}
            .faint {{ color: #868e96; font-size: 12px; }}
            ul {{ margin-top: 6px; }}
        </style>
    </head>
    <body>
        <h1>Market Research Executive Dashboard</h1>
        <p><b>Generated At:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST &nbsp;|&nbsp;
           <b>Analysis Window:</b> {start_date} to {end_date}</p>

        <div class="card">
            <h2>Market Snapshot (As of {snapshot['latest_date']})</h2>
            <p class="scope-note">Nifty Close and India VIX are latest-day values. Tracking Peak and Drawdown are calculated across the <b>entire database history</b> ({snapshot['history_start']} to {snapshot['latest_date']}, {snapshot['history_days']} trading days) — not the 30-day window used in the sections below.</p>
            <div class="metric-grid">
                {metric('Nifty Close (Latest Day)', f"{snapshot['latest_close']:.2f}")}
                {metric('Tracking Peak (All-Time)', f"{snapshot['peak_close']:.2f}")}
                {metric('Drawdown from All-Time Peak', f"{snapshot['current_dd']:.2f}%", 'neg')}
                {metric('India VIX (Latest Day)', f"{snapshot['latest_vix']:.2f}")}
            </div>
        </div>

        {fii_dii_html}
        {sector_html}
        {events_html}
        {prediction_html}
        {structure_html}
        {global_html}
        {learnings_html}
        {macro_html}

        <div class="card">
            <h2>Permanent Archive Row Counts (All-Time, Entire Database)</h2>
            <ul>
                <li><b>Daily Market Data:</b> {counts['daily_data']} trading days</li>
                <li><b>Market Vibe / Global Sentiment:</b> {counts['market_vibe']} rows</li>
                <li><b>Sector Logs:</b> {counts['sectors']} entries</li>
                <li><b>Market Events:</b> {counts['events']} events</li>
                <li><b>Learnings & Journal Entries:</b> {counts['learnings']} entries</li>
            </ul>
        </div>
    </body>
    </html>
    """

    return html_content


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def generate_dashboard():
    conn = sqlite3.connect(DB_PATH)

    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
        for table in ["daily_data", "market_vibe", "sectors", "events", "learnings"]
    }

    rows = conn.execute("SELECT date, nifty_close, vix_close FROM daily_data ORDER BY date ASC;").fetchall()
    latest_date, latest_close, latest_vix = rows[-1]
    peak_close = max(r[1] for r in rows if r[1] is not None)
    current_dd = ((latest_close - peak_close) / peak_close) * 100
    snapshot = {
        "latest_date": latest_date,
        "latest_close": latest_close,
        "latest_vix": latest_vix,
        "peak_close": peak_close,
        "current_dd": current_dd,
        "history_start": rows[0][0],
        "history_days": len(rows),
    }

    start_date, end_date = window_bounds(conn)

    fii_dii = fii_dii_summary(conn, start_date, end_date)
    sector = sector_performance(conn, start_date, end_date)
    events = event_category_summary(conn, start_date, end_date)
    prediction = prediction_hit_analysis(conn, start_date, end_date)
    structure = market_structure_summary(conn, start_date, end_date)
    global_cues = global_cues_correlation(conn, start_date, end_date)
    learnings = learnings_digest(conn, start_date, end_date)
    macro = macro_context(conn, start_date, end_date)

    conn.close()

    html_content = render_dashboard(
        counts, snapshot, fii_dii, sector, events, prediction,
        structure, global_cues, learnings, macro, start_date, end_date,
    )

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(html_content, encoding="utf-8")
    print(f"Executive HTML Dashboard generated at: {REPORT_PATH}")


if __name__ == "__main__":
    generate_dashboard()