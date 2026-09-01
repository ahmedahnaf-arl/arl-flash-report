"""
ARL Live Flash Report Server
Usage: python live_server.py [--port PORT]
Auto-detects T-1 date, queries DWH live, renders HTML with Canvas charts.
"""
import http.server
import json
import os
import sys
import re
import threading
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from socketserver import ThreadingMixIn

PORT = 8765
HOST = "0.0.0.0"  # Bind to all interfaces for LAN + tunnel access
ROOT = Path(__file__).parent.resolve()

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=203.202.241.211,1433;"
    "DATABASE=DWH;UID=mcp_user;PWD=iAOS@35o997;Encrypt=no;TrustServerCertificate=yes;"
    "Connection Timeout=30;"
)

def fmt(n, d=2):
    if n is None: return "—"
    try:
        s = f"{n:,.{d}f}"
        return s
    except (ValueError, TypeError):
        return "—"

def pct(a, b):
    if not b or b == 0: return None
    return ((a / b) - 1) * 100

def js_sig(v):
    if v is None: return "'N/A'"
    if v >= 20: return "'Strong +'"
    if v >= 0: return "'Positive'"
    if v >= -15: return "'Neutral'"
    if v >= -30: return "'Weak'"
    return "'Negative'"

def js(obj):
    if isinstance(obj, dict):
        return "{" + ",".join(f"{k}:{js(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return "[" + ",".join(js(i) for i in obj) + "]"
    if isinstance(obj, str):
        return f"'{obj}'"
    if obj is None:
        return "null"
    return str(obj)

def get_conn():
    # Cloud mode: DWH creds from environment (self-hosted runner uses pymssql)
    if os.environ.get("DWH_SERVER"):
        import pymssql
        return pymssql.connect(
            server=os.environ["DWH_SERVER"],
            port=int(os.environ.get("DWH_PORT", "1433")),
            user=os.environ["DWH_USER"],
            password=os.environ["DWH_PASSWORD"],
            database="DWH",
            timeout=120,
            login_timeout=30,
        )
    # Local mode: ODBC driver
    import pyodbc
    conn = pyodbc.connect(CONN_STR)
    conn.timeout = 120
    return conn

def detect_report_date():
    """Always return T-1 (yesterday) for a complete-day report."""
    return date.today() - timedelta(days=1)

def get_report_data(report_date):
    """Run ALL DWH queries and return structured data."""
    rd = report_date
    de = rd.day  # days elapsed
    dm = 31  # Will auto-detect, but Aug = 31
    mf = round(de / dm, 10)

    # Determine days in month
    import calendar
    dm = calendar.monthrange(rd.year, rd.month)[1]
    de = rd.day
    mf = round(de / dm, 10)

    # Previous month for MoM
    if rd.month == 1:
        prev_month = 12
        prev_year = rd.year - 1
    else:
        prev_month = rd.month - 1
        prev_year = rd.year

    # Same period last year
    yoy_year = rd.year - 1

    # FY start
    if rd.month >= 7:
        fy_year = rd.year
    else:
        fy_year = rd.year - 1

    rd_str = rd.strftime("%Y-%m-%d")
    next_str = (rd + timedelta(days=1)).strftime("%Y-%m-%d")
    month_start = rd.strftime("%Y-%m-01")
    prev_start = f"{prev_year}-{prev_month:02d}-01"
    prev_end = (date(prev_year, prev_month, 1) + timedelta(days=de)).strftime("%Y-%m-%d")
    yoy_start = f"{yoy_year}-{rd.month:02d}-01"
    yoy_end = (date(yoy_year, rd.month, 1) + timedelta(days=de)).strftime("%Y-%m-%d")
    fy_start = f"{fy_year}-07-01"
    cy_start = f"{rd.year}-01-01"

    conn = get_conn()
    c = conn.cursor()

    # 1. Revenue sub-schedule (net of returns; SBU 0 = unallocated cement -> ACCL 58)
    c.execute(f"""
        SELECT CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END AS sbu,
          SUM(CASE WHEN CAST(j.dteTransactionDate AS DATE)='{rd_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS daily,
          SUM(CASE WHEN CAST(j.dteTransactionDate AS DATE)='{(rd - timedelta(days=1)).strftime("%Y-%m-%d")}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS dod,
          SUM(CASE WHEN j.dteTransactionDate>='{month_start}' AND j.dteTransactionDate<'{next_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS mtd,
          SUM(CASE WHEN j.dteTransactionDate>='{prev_start}' AND j.dteTransactionDate<'{prev_end}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS mom,
          SUM(CASE WHEN j.dteTransactionDate>='{yoy_start}' AND j.dteTransactionDate<'{yoy_end}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS yoy,
          SUM(CASE WHEN j.dteTransactionDate>='{fy_start}' AND j.dteTransactionDate<'{next_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS fy_ytd,
          SUM(CASE WHEN j.dteTransactionDate>='{cy_start}' AND j.dteTransactionDate<'{next_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS cy_ytd
        FROM DWH.fin.tblAccountingJournalArc j
        WHERE j.strGeneralLedgerCode IN ('3010001','3010002','3010005','3010006') AND j.isActive=1
          AND j.intSBUId NOT IN (103,116,119,122,111)
        GROUP BY CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END ORDER BY sbu
    """)
    gl_rows = {row[0]: {
        'd': round(row[1], 6) if row[1] else 0,
        'dod': round(row[2], 6) if row[2] else 0,
        'm': round(row[3], 6) if row[3] else 0,
        'mom': round(row[4], 6) if row[4] else 0,
        'yoy': round(row[5], 6) if row[5] else 0,
        'fy': round(row[6], 6) if row[6] else 0,
        'cy': round(row[7], 6) if row[7] else 0,
    } for row in c.fetchall()}

    # 2. GL 3010005 freight SBUs (net)
    c.execute(f"""
        SELECT j.intSBUId,
          SUM(CASE WHEN CAST(j.dteTransactionDate AS DATE)='{rd_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS daily,
          SUM(CASE WHEN CAST(j.dteTransactionDate AS DATE)='{(rd - timedelta(days=1)).strftime("%Y-%m-%d")}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS dod,
          SUM(CASE WHEN j.dteTransactionDate>='{month_start}' AND j.dteTransactionDate<'{next_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS mtd
        FROM DWH.fin.tblAccountingJournalArc j
        WHERE j.strGeneralLedgerCode='3010005' AND j.isActive=1
          AND j.intSBUId IN (64,79,80,81,88,110)
          AND j.dteTransactionDate>='{month_start}' AND j.dteTransactionDate<'{next_str}'
        GROUP BY j.intSBUId ORDER BY j.intSBUId
    """)
    fr_d = {}; fr_m = {}
    for row in c.fetchall():
        fr_d[row[0]] = round(row[1], 6) if row[1] else 0
        fr_m[row[0]] = round(row[3], 6) if row[3] else 0

    # 3. Reconciliation totals (net of returns)
    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010001' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g1all = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010001' AND isActive=1 AND intSBUId IN (103,116,119,122,111) AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    excl = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010005' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g5all = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010002' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g2all = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010006' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g6all = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010004' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g4all = round(c.fetchone()[0] or 0, 6)

    # 4. Daily volumes
    c.execute(f"""
        SELECT h.intBusinessAreaId,
          SUM(CASE WHEN ri.strUOM='Kilogram' THEN ri.numQuantity/1000.0 WHEN ri.strUOM IN ('Ton','Metric Ton') THEN ri.numQuantity WHEN ri.strUOM='Litre' THEN ri.numQuantity/1000.0 ELSE ri.numQuantity END)
        FROM DWH.sms.tblDeliveryHeaderArc h
        JOIN DWH.sms.tblDeliveryRowArc ri ON h.intDeliveryId=ri.intDeliveryId
        JOIN DWH.itm.tblItemArc i ON ri.intItemId=i.intItemId
        WHERE h.dteDeliveryDate='{rd_str}' AND h.intBusinessAreaId NOT IN (103,116,119,122,111)
        GROUP BY h.intBusinessAreaId
    """)
    dv = {row[0]: round(row[1], 2) for row in c.fetchall() if row[1]}

    # 5. MTD volumes
    c.execute(f"""
        SELECT h.intBusinessAreaId,
          SUM(CASE WHEN ri.strUOM='Kilogram' THEN ri.numQuantity/1000.0 WHEN ri.strUOM IN ('Ton','Metric Ton') THEN ri.numQuantity WHEN ri.strUOM='Litre' THEN ri.numQuantity/1000.0 ELSE ri.numQuantity END)
        FROM DWH.sms.tblDeliveryHeaderArc h
        JOIN DWH.sms.tblDeliveryRowArc ri ON h.intDeliveryId=ri.intDeliveryId
        JOIN DWH.itm.tblItemArc i ON ri.intItemId=i.intItemId
        WHERE h.dteDeliveryDate>='{month_start}' AND h.dteDeliveryDate<'{next_str}' AND h.intBusinessAreaId NOT IN (103,116,119,122,111)
        GROUP BY h.intBusinessAreaId
    """)
    mv = {row[0]: round(row[1], 2) for row in c.fetchall() if row[1]}

    # 6. MoM volumes
    c.execute(f"""
        SELECT h.intBusinessAreaId,
          SUM(CASE WHEN ri.strUOM='Kilogram' THEN ri.numQuantity/1000.0 WHEN ri.strUOM IN ('Ton','Metric Ton') THEN ri.numQuantity WHEN ri.strUOM='Litre' THEN ri.numQuantity/1000.0 ELSE ri.numQuantity END)
        FROM DWH.sms.tblDeliveryHeaderArc h
        JOIN DWH.sms.tblDeliveryRowArc ri ON h.intDeliveryId=ri.intDeliveryId
        JOIN DWH.itm.tblItemArc i ON ri.intItemId=i.intItemId
        WHERE h.dteDeliveryDate>='{prev_start}' AND h.dteDeliveryDate<'{prev_end}' AND h.intBusinessAreaId NOT IN (103,116,119,122,111)
        GROUP BY h.intBusinessAreaId
    """)
    mov = {row[0]: round(row[1], 2) for row in c.fetchall() if row[1]}

    # 7. ABSL channel split
    c.execute(f"""
        SELECT h.intDistributionChannelId, SUM(h.numTotalNetValue)/10000000.0
        FROM DWH.sms.tblDeliveryHeaderArc h
        WHERE h.dteDeliveryDate>='{month_start}' AND h.dteDeliveryDate<'{next_str}'
          AND h.intBusinessAreaId=98 AND h.intDistributionChannelId IN (111,128,129)
        GROUP BY h.intDistributionChannelId
    """)
    asphalt_rev = 0; benzol_rev = 0
    for row in c.fetchall():
        if row[0] == 111: asphalt_rev = row[1]
        elif row[0] in (128, 129): benzol_rev += row[1]
    total_del = asphalt_rev + benzol_rev
    asphalt_ratio = round(asphalt_rev / total_del, 4) if total_del > 0 else 0.74
    benzol_ratio = round(benzol_rev / total_del, 4) if total_del > 0 else 0.26

    # 8. Daily trends (GL revenue sub-schedule, net)
    c.execute(f"""
        SELECT CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END AS sbu, CAST(j.dteTransactionDate AS DATE) AS dt, SUM(-j.numAmount)/10000000.0 AS daily_rev
        FROM DWH.fin.tblAccountingJournalArc j
        WHERE j.strGeneralLedgerCode IN ('3010001','3010002','3010005','3010006') AND j.isActive=1
          AND j.dteTransactionDate>='{month_start}' AND j.dteTransactionDate<'{next_str}'
          AND j.intSBUId NOT IN (103,116,119,122,111)
        GROUP BY CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END, CAST(j.dteTransactionDate AS DATE)
        ORDER BY sbu, dt
    """)
    td = [{'d': str(row[1]), 's': row[0], 'v': round(row[2], 6)} for row in c.fetchall()]

    # 9. Targets (Aug-26 from Google Sheets Target_Input sheet, file 1kf-2lI17nMgHx2bXAvwwx9PWboZ09qFmKP7NCR5hX3A)
    targets = {'AIL': 121.00, 'ACCL': 173.00, 'AEL': 180.00, 'ARMCL': 37.91, 'Orca': 1.10,
               'AAFL': 103.80, 'Benzol': 2.61, 'ABSL_Asphalt': 8.99, 'ACL': 1.90, 'ALEL': 19.73,
               'NTL': 45.75, 'APFIL': 22.17, 'AITL': 3.85, 'BPL': 6.00, 'BTL_Coal': 18.71,
               'AEFL': 2.29, 'ABL': 2.32, 'AAIL': 4.53, 'DTL_Coal': 37.50}

    # 10. SBU Map
    sbu_map = {19: 'APFIL', 36: 'AEL', 58: 'ACCL', 64: 'ASLL', 69: 'ARMCL', 72: 'BTL_Coal',
               77: 'DTL_Coal', 79: 'AOCN', 80: 'ASLL-1', 81: 'AMTL', 82: 'iBOS', 83: 'BPL',
               84: 'AITL', 86: 'HRML', 87: 'FAL', 88: 'ASeLL', 91: 'NTL', 98: 'ABSL',
               99: 'ACL', 102: 'AIL', 109: 'AAFL', 110: 'ASeLLC', 114: 'ALEL', 115: 'AAIL', 118: 'ATL',
               120: 'AEFL', 123: 'AEL_Eng', 124: 'ABL', 126: 'Orca', 128: 'AMXL', 129: 'NJL', 132: 'AMPL'}

    conn.close()

    # Freight defaults
    for sbu_id in [64, 79, 80, 81, 88, 110]:
        if sbu_id not in fr_d:
            fr_d[sbu_id] = 0
            fr_m[sbu_id] = 0
        if sbu_id not in gl_rows:
            gl_rows[sbu_id] = {'d': 0, 'dod': 0, 'm': 0, 'mom': 0, 'yoy': 0, 'fy': 0, 'cy': 0}

    # Compute reconciliation
    rpt_gl1 = round(g1all - excl, 6)
    rpt_frt = round(sum(fr_m.values()), 6)
    rpt_tot = round(rpt_gl1 + rpt_frt, 6)
    full_tot = round(g1all + g5all + g2all + g6all + g4all, 6)
    gap = round(full_tot - rpt_tot, 6)

    month_pct = round(mf * 100, 1)
    period = f"{rd.strftime('%b')} 1–{de}"
    day_label = f"{de}/{dm}"

    return {
        'report_date': rd,
        'rd_str': rd_str,
        'de': de, 'dm': dm, 'mf': mf, 'month_pct': month_pct,
        'period': period, 'day_label': day_label,
        'gl': gl_rows, 'fr_d': fr_d, 'fr_m': fr_m,
        'dv': dv, 'mv': mv, 'mov': mov, 'td': td,
        'g1all': g1all, 'excl': excl, 'g5all': g5all, 'g2all': g2all, 'g6all': g6all, 'g4all': g4all,
        'rpt_gl1': rpt_gl1, 'rpt_frt': rpt_frt, 'rpt_tot': rpt_tot,
        'full_tot': full_tot, 'gap': gap,
        'asphalt': asphalt_ratio, 'benzol': benzol_ratio,
        'targets': targets, 'sbu_map': sbu_map,
    }

def build_html(data):
    """Generate the complete self-contained HTML with all data embedded."""
    rd = data['report_date']
    date_str = rd.strftime("%B %d, %Y")
    title_date = rd.strftime("%b %d, %Y")

    de = data['de']; dm = data['dm']; mf = data['mf']
    month_pct = data['month_pct']

    # Format trend data as JS
    td_js = js(data['td'])

    # Compute KPI totals
    total_daily = 0; total_mtd = 0; total_fy = 0; total_cy = 0; ach_list = []
    for sid, g in data['gl'].items():
        daily = (g['d'] or 0)
        mtd = (g['m'] or 0)
        total_daily += daily; total_mtd += mtd
        total_fy += (g['fy'] or 0); total_cy += (g['cy'] or 0)
        # Ach% available from JS-side computation only — skip Python check

    proj_me = round(total_mtd / de * dm, 2) if de > 0 else 0
    run_rate = round(total_mtd / de, 2) if de > 0 else 0

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARL Daily SBU Sales Flash Report — {title_date}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;font-size:17px}}
#app{{padding:1.5rem 2rem;max-width:1500px;margin:0 auto}}
#loading{{text-align:center;padding:3rem;color:#94a3b8;font-size:1.15rem}}
header{{border-bottom:1px solid #334155;padding-bottom:1rem;margin-bottom:1.5rem}}
header h1{{font-size:1.8rem;color:#f8fafc}}
header .meta{{color:#94a3b8;font-size:1rem;margin-top:0.25rem}}
.kpi-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-bottom:1.5rem}}
.kpi-card{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1.1rem;text-align:center;transition:transform 0.2s,box-shadow 0.2s}}
.kpi-card:hover{{transform:translateY(-2px);box-shadow:0 6px 16px rgba(0,0,0,0.4)}}
.kpi-card .label{{color:#94a3b8;font-size:0.9rem;text-transform:uppercase;letter-spacing:0.05rem}}
.kpi-card .val{{font-size:1.85rem;font-weight:700;color:#f8fafc;margin:0.3rem 0;animation:kpiPop 0.6s ease-out}}
.kpi-card .sub{{font-size:0.9rem;color:#94a3b8}}
@keyframes kpiPop{{0%{{transform:scale(0.92);opacity:0.4}}60%{{transform:scale(1.04)}}100%{{transform:scale(1);opacity:1}}}}
@media (max-width:768px){{.kpi-row{{grid-template-columns:repeat(2,1fr)}}.charts-row{{grid-template-columns:1fr}}.insights-row{{grid-template-columns:1fr}}.summary-chart-box .canvas-row{{flex-direction:column;align-items:center}}.canvas-row canvas{{width:100%;height:auto}}.recon-grid{{grid-template-columns:1fr}}}}
@media (max-width:480px){{.kpi-row{{grid-template-columns:1fr}}}}
.charts-row{{display:grid;grid-template-columns:2fr 1fr;gap:1rem;margin-bottom:1.5rem}}
.chart-box{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1rem;box-shadow:0 4px 12px rgba(0,0,0,0.25);transition:box-shadow 0.2s}}
.chart-box:hover{{box-shadow:0 6px 20px rgba(56,189,248,0.08)}}
.chart-box h3{{font-size:1.05rem;color:#94a3b8;margin-bottom:0.75rem;text-transform:uppercase}}
.bar-wrap{{display:flex;flex-direction:column;gap:5px}}
.bar-item{{display:flex;align-items:center;gap:0.5rem}}
.bar-item .lbl{{width:90px;font-size:0.9rem;text-align:right;color:#94a3b8;flex-shrink:0}}
.bar-item .bar-bg{{flex:1;height:20px;background:#1e293b;border-radius:3px;overflow:hidden;position:relative}}
.bar-item .bar-fill{{height:100%;border-radius:3px;transition:width 0.5s}}
.bar-item .bar-val{{width:80px;font-size:0.9rem;color:#cbd5e1;flex-shrink:0;text-align:right}}
.insights-row{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-bottom:1.5rem}}
.insight-box{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1rem}}
.insight-box h3{{font-size:1rem;color:#f8fafc;margin-bottom:0.75rem;padding-bottom:0.5rem;border-bottom:1px solid #334155}}
.insight-box ul{{list-style:none;font-size:0.95rem;line-height:1.6}}
.insight-box li{{color:#cbd5e1;padding:0.2rem 0}}
.insight-box li.neg{{color:#fca5a5}}
.insight-box li.pos{{color:#86efac}}
.recon-card{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1.5rem;margin-bottom:1.5rem}}
.recon-card h3{{color:#38bdf8;margin-bottom:1rem;font-size:1.15rem}}
.recon-grid{{display:grid;grid-template-columns:1fr 1fr;gap:2rem}}
.recon-col h4{{color:#94a3b8;font-size:0.95rem;text-transform:uppercase;margin-bottom:0.75rem}}
.recon-col table{{width:100%;font-size:1rem}}
.recon-col td{{padding:0.35rem 0.5rem;color:#cbd5e1}}
.recon-col .total td{{border-top:1px solid #475569;font-weight:700;color:#f8fafc}}
.recon-col .val{{text-align:right;font-family:monospace}}
.recon-note{{color:#fbbf24;font-size:0.95rem;margin-top:1rem;padding:0.6rem;background:#422006;border-radius:0.5rem}}
.scorecard-table{{width:100%;border-collapse:collapse;font-size:0.98rem;background:#1e293b;border-radius:0.75rem;overflow:hidden;border:1px solid #334155}}
.scorecard-table th{{background:#0f172a;color:#94a3b8;padding:0.6rem 0.5rem;text-align:left;font-weight:600;position:sticky;top:0;z-index:2;font-size:0.9rem;text-transform:uppercase}}
.scorecard-table th.num{{text-align:right}}
.scorecard-table td{{padding:0.55rem 0.6rem;border-bottom:1px solid #1e293b;transition:background 0.15s}}
.scorecard-table tbody tr{{transition:box-shadow 0.15s}}
.scorecard-table tbody tr:hover{{background:#1e3a5f;box-shadow:inset 3px 0 0 #38bdf8}}
.scorecard-table tbody tr.top-performer{{background:#1a2f1a}}
.scorecard-table tbody tr.top-performer:hover{{background:#1e3a2e;box-shadow:inset 3px 0 0 #4ade80}}
.scorecard-table td.num{{text-align:right;font-family:monospace}}
.scorecard-wrap{{overflow-x:auto;border-radius:0.75rem;margin-bottom:1.5rem;-webkit-overflow-scrolling:touch}}
.scorecard-controls{{display:flex;gap:0.75rem;margin-bottom:0.75rem;align-items:center;flex-wrap:wrap}}
.scorecard-controls select,.scorecard-controls input{{background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:0.5rem;padding:0.5rem 0.85rem;font-size:0.95rem}}
.scorecard-controls select:focus,.scorecard-controls input:focus{{outline:none;border-color:#38bdf8}}
.scorecard-controls input{{min-width:220px}}
.scorecard-controls label{{color:#94a3b8;font-size:0.9rem;margin-right:0.25rem}}
.chart-stats{{display:flex;gap:1rem;margin-bottom:0.75rem;font-size:0.9rem;color:#94a3b8;flex-wrap:wrap}}
.chart-stats span{{background:#0f172a;padding:0.25rem 0.6rem;border-radius:0.35rem;border:1px solid #334155}}
.chart-stats b{{color:#38bdf8}}
.mom-up{{color:#4ade80}}
.mom-down{{color:#f87171}}
.mom-neu{{color:#fbbf24}}
footer{{text-align:center;color:#64748b;font-size:0.85rem;padding:1.5rem 0;border-top:1px solid #1e293b;margin-top:1.5rem}}
.flag-card{{background:#451a03;border:1px solid #d97706;border-radius:0.75rem;padding:1rem;margin-bottom:1rem;font-size:0.95rem;color:#fcd34d}}
.flag-card b{{color:#fbbf24}}
.vol-cell{{color:#7dd3fc}}
.chart-toggle{{cursor:pointer;color:#38bdf8;font-size:0.85rem;display:inline-block;margin-left:0.3rem;transition:transform 0.2s}}
.chart-toggle.open{{transform:rotate(90deg)}}
.chart-row{{display:none}}
.chart-row.open{{display:table-row}}
.chart-row td{{padding:0;border:none;background:#0f172a}}
.chart-canvas-wrap{{padding:0.75rem 1rem}}
.chart-canvas-wrap canvas{{background:#1a2332;border-radius:0.5rem;border:1px solid #334155;cursor:pointer}}
.summary-chart-box{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1rem;margin-bottom:1.5rem;box-shadow:0 4px 12px rgba(0,0,0,0.25)}}
.summary-chart-box h3{{font-size:1.05rem;color:#94a3b8;margin-bottom:0.75rem;text-transform:uppercase}}
.summary-chart-box .canvas-row{{display:flex;gap:1rem;flex-wrap:wrap;justify-content:center}}
.summary-chart-box canvas{{background:#1a2332;border-radius:0.5rem;border:1px solid #334155;cursor:crosshair}}
#login-overlay{{position:fixed;inset:0;background:rgba(15,23,42,0.98);z-index:9999;display:flex;align-items:center;justify-content:center;flex-direction:column}}
#login-overlay.hidden{{display:none}}
#login-box{{background:#1e293b;padding:2.5rem;border-radius:1rem;border:1px solid #334155;width:380px;text-align:center}}
#login-box h2{{color:#38bdf8;margin-bottom:0.5rem;font-size:1.5rem}}
#login-box p{{color:#94a3b8;margin-bottom:1.5rem;font-size:1rem}}
#login-box input{{width:100%;padding:0.85rem;margin:0.35rem 0;border-radius:0.5rem;border:1px solid #475569;background:#0f172a;color:#e2e8f0;font-size:1.05rem}}
#login-box input:focus{{outline:none;border-color:#38bdf8}}
#login-box button{{width:100%;padding:0.85rem;margin-top:1rem;background:#38bdf8;color:#0f172a;border:none;border-radius:0.5rem;font-weight:700;font-size:1.15rem;cursor:pointer}}
#login-box .err{{color:#f87171;margin-top:0.5rem;font-size:0.95rem}}
#loading-overlay{{position:fixed;inset:0;background:rgba(15,23,42,0.95);z-index:9998;display:flex;align-items:center;justify-content:center;flex-direction:column;color:#94a3b8;font-size:1.25rem}}
#loading-overlay.hidden{{display:none}}
.spinner{{width:40px;height:40px;border:3px solid #334155;border-top:3px solid #38bdf8;border-radius:50%;animation:spin 1s linear infinite;margin-bottom:1rem}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style>
</head>
<body>
<div id="login-overlay"><div id="login-box">
<h2>ARL Flash Report</h2><p>{date_str}</p>
<input type="text" id="un" placeholder="Username"><input type="password" id="pw" placeholder="Password">
<button onclick="auth()">Sign In</button><div class="err" id="login-err"></div>
</div></div>
<div id="loading-overlay"><div class="spinner"></div><span>Querying DWH live... this may take 30-45 seconds</span></div>
<div id="app">
<header>
<h1>AKIJ RESOURCE — Daily SBU Sales Flash Report</h1>
<div class="meta">Report Date: {date_str} | Period: {data['period']} (Day {data['day_label']}, {month_pct}%) | Source: DWH GL 3010001–3010006 (Revenue sub-schedule) | FY 2026-27 | Live</div>
</header>

<div class="flag-card">
<b>Basis:</b> Revenue = net of sales returns (GL 3010001–3010006, credits − debits). Unallocated cement deliveries (intSBUId=0) mapped to ACCL (58). <b>Overrides still needed:</b> ABL (124) and Orca (126) have persistent gaps vs portal. BTL_G2G dormant since Jul 2026.
</div>

<div class="kpi-row" id="kpi-row"></div>

<div class="summary-chart-box">
<h3>Portfolio Daily Revenue Trend — {data['period']} (BDT Cr)</h3>
<div class="chart-stats" id="portfolio-stats"></div>
<div class="canvas-row">
<canvas id="portfolio-daily" width="640" height="280"></canvas>
<canvas id="top5-stacked" width="440" height="280"></canvas>
</div>
</div>

<div class="charts-row">
<div class="chart-box"><h3>MTD Revenue — Top 15 SBUs (Cr)</h3><div class="bar-wrap" id="mtd-chart"></div></div>
<div class="chart-box"><h3>MoM Momentum Distribution</h3><div class="bar-wrap" id="mom-chart"></div></div>
</div>

<div class="insights-row" id="insights-row"></div>

<div class="recon-card">
<h3>Revenue Reconciliation — MTD {data['period']}</h3>
<div class="recon-grid">
<div class="recon-col">
<h4>Our Report Total (sub-schedule)</h4>
<table>
<tr><td>GL 3010001 Sales (Local)</td><td class="val" id="rpt-gross">—</td></tr>
<tr><td style="font-size:0.9rem;color:#94a3b8;padding-left:1.5rem">Report SBUs excl. recon (103,116,119,122,111)</td></tr>
<tr><td>GL 3010005 Freight (ASLL, AOCN, AMTL, ASeLL, ASLL-1, ASeLLC)</td><td class="val" id="rpt-freight">—</td></tr>
<tr class="total"><td>Report Total</td><td class="val" id="rpt-total">—</td></tr>
</table>
</div>
<div class="recon-col">
<h4>Full GL Revenue (sub-schedule)</h4>
<table>
<tr><td>GL 3010001 Sales (Local)</td><td class="val" id="full-3010001">—</td></tr>
<tr><td>GL 3010002 Sales (Foreign)</td><td class="val" id="full-3010002">—</td></tr>
<tr><td>GL 3010005 Freight Income</td><td class="val" id="full-3010005">—</td></tr>
<tr><td>GL 3010006 Agency Income</td><td class="val" id="full-3010006">—</td></tr>
<tr><td>GL 3010004 Other Income</td><td class="val" id="full-3010004">—</td></tr>
<tr class="total"><td>Full GL Total</td><td class="val" id="full-total">—</td></tr>
</table>
</div>
</div>
<div class="recon-note" id="recon-note"></div>
</div>

<div class="scorecard-controls">
<label>Sort by:</label>
<select id="scorecard-sort" onchange="sortScorecard()">
<option value="mtd_rev">MTD Revenue (default)</option>
<option value="daily_rev">Daily Revenue</option>
<option value="code">SBU Code A–Z</option>
<option value="mtd_ach_pct">Ach% High–Low</option>
<option value="mom_pct">MoM% High–Low</option>
<option value="yoy_pct">YoY% High–Low</option>
<option value="proj_rev">Projected M/E</option>
</select>
<input type="text" id="scorecard-filter" placeholder="Filter SBUs..." oninput="filterScorecard()">
</div>
<div class="scorecard-wrap">
<table class="scorecard-table">
<thead>
<tr>
<th>SBU</th><th class="num">Daily Rev</th><th class="num">DoD%</th><th class="num">MTD Rev</th><th class="num">MTD Tgt</th><th class="num">Ach%</th>
<th class="num">MoM%</th><th class="num">YoY%</th><th class="num">FY YTD</th><th class="num">CY YTD</th><th class="num">Proj M/E</th><th>Signal</th>
<th class="num">MTD Vol</th><th class="num">Daily Vol</th><th></th></tr>
</thead>
<tbody id="scorecard-body"></tbody>
</table>
</div>
<footer>Powered by ARL Live Flash Report Engine · DWH GL 3010001–3010006 (Revenue sub-schedule) · sms.tblDeliveryHeaderArc · Generated live on {date_str} · Next refresh: reload page</footer>
</div>

<script>
const CREDS={{ 'arl.admin':'Flash@2026', 'cbdo':'CBDO@ARL26' }};
function auth(){{
  let u=document.getElementById('un').value.trim(), p=document.getElementById('pw').value;
  if(CREDS[u]===p){{ document.getElementById('login-overlay').classList.add('hidden'); sessionStorage.setItem('arl_flash_auth','1'); }}
  else document.getElementById('login-err').textContent='Invalid credentials';
}}
window.addEventListener('DOMContentLoaded',()=>{{ if(sessionStorage.getItem('arl_flash_auth')) document.getElementById('login-overlay').classList.add('hidden'); }});
document.getElementById('pw').addEventListener('keydown',e=>{{ if(e.key==='Enter') auth(); }});
const DE={de}, DM={dm};
const M_FACTOR={mf};
const SBU_MAP={js(data['sbu_map'])};
const MONTH_TARGETS={js(data['targets'])};
const TD={td_js};
const FR_D={js(data['fr_d'])};
const FR_M={js(data['fr_m'])};
const DV={js(data['dv'])};
const MV={js(data['mv'])};
const MOV={js(data['mov'])};
const GL={js(data['gl'])};
const ABSL_ASPH={data['asphalt']}, ABSL_BENZ={data['benzol']};
const FREIGHT_IDS=new Set([64,79,80,81,88,110]);
const RECON={{g1all:{data['g1all']},excl:{data['excl']},g5all:{data['g5all']},g2all:{data['g2all']},g6all:{data['g6all']},g4all:{data['g4all']},
  rpt_gl1:{data['rpt_gl1']},rpt_frt:{data['rpt_frt']},rpt_tot:{data['rpt_tot']},full_tot:{data['full_tot']},gap:{data['gap']}}};

function fmt(n,d){{ if(n==null||isNaN(n)) return '—'; let s=n.toFixed(d||2); return s.replace(/\\B(?=(\\d{{3}})+(?!\\d))/g,',') }}
function pct(a,b){{ if(!b||b===0) return null; return ((a/b)-1)*100 }}
function momSig(v){{ if(v==null||isNaN(v)) return 'N/A'; if(v>=20) return 'Strong +'; if(v>=0) return 'Positive'; if(v>=-15) return 'Neutral'; if(v>=-30) return 'Weak'; return 'Negative' }}
function momCls(v){{ if(v==null||isNaN(v)) return 'mom-neu'; if(v>=20) return 'mom-up'; if(v>=0) return 'mom-up'; if(v>=-15) return 'mom-neu'; return 'mom-down' }}

function buildSBU(id){{
  let g=GL[id], name=SBU_MAP[id], fr_d=FR_D[id]||0, fr_m=FR_M[id]||0;
  let daily=(g?(g.d||0):0);
  let mtd=(g?(g.m||0):0);
  let dod=((g?g.dod:0)||0);
  let dv=DV[id]||0, mv=MV[id]||0, movv=MOV[id]||0;
  let has_vol=mv>0||!!DV[id];
  if(id===98){{ return [buildChannel(id,'ABSL Asphalt',ABSL_ASPH), buildChannel(id,'ABSL Benzol',ABSL_BENZ)]; }}
  let moTgt=MONTH_TARGETS[name]||null;
  let mtdTgt=moTgt?(moTgt*M_FACTOR):null;
  let ach=(mtdTgt&&mtd>0)?(mtd/mtdTgt*100):null;
  let momPct=(g?g.mom:0)>0?pct(mtd,(g?g.mom:0)):null;
  let yoyPct=(g?g.yoy:0)>0?pct(mtd,(g?g.yoy:0)):null;
  let proj=mtd>0?(mtd/DE*DM):0;
  return [{{id,code:name,name,src:'GL 3010001-06',
    daily_rev:daily,dod_rev:dod,mtd_rev:mtd,mom_rev:(g?g.mom:0)||0,
    yoy_rev:(g?g.yoy:0)||0,fy_ytd_rev:(g?g.fy:0)||0,cy_ytd_rev:(g?g.cy:0)||0,
    daily_vol:dv,mtd_vol:mv,mom_vol:movv,has_vol:has_vol,
    mtd_tgt_rev:mtdTgt,mo_tgt_rev:moTgt,
    mtd_ach_pct:ach,mom_pct:momPct,yoy_pct:yoyPct,
    proj_rev:proj,momentum:momSig(momPct),tgt:moTgt?('MTD='+fmt(mtdTgt)):'—'}}];
}}

function buildChannel(id,name,ratio){{
  let g=GL[id], base=g||{{}};
  let daily=(base.d||0)*ratio, mtd=(base.m||0)*ratio;
  let dod=(base.dod||0)*ratio, mom=(base.mom||0)*ratio, yoy=(base.yoy||0)*ratio;
  let fy=(base.fy||0)*ratio, cy=(base.cy||0)*ratio;
  let moTgt=name==='ABSL Asphalt'?MONTH_TARGETS['ABSL_Asphalt']:MONTH_TARGETS['Benzol'];
  let mtdTgt=moTgt?moTgt*M_FACTOR:null;
  let ach=mtdTgt&&mtd>0?(mtd/mtdTgt*100):null;
  let proj=mtd>0?(mtd/DE*DM):0;
  let momPct=mom>0?pct(mtd,mom):null;
  return {{id,code:name,name,src:'GL 3010001',
    daily_rev:daily,dod_rev:dod,mtd_rev:mtd,mom_rev:mom,
    yoy_rev:yoy,fy_ytd_rev:fy,cy_ytd_rev:cy,
    daily_vol:0,mtd_vol:0,mom_vol:0,has_vol:false,
    mtd_tgt_rev:mtdTgt,mo_tgt_rev:moTgt,
    mtd_ach_pct:ach,mom_pct:momPct,yoy_pct:null,
    proj_rev:proj,momentum:momSig(momPct),tgt:moTgt?('MTD='+fmt(mtdTgt)):'—'}};
}}

let ALL=[];
let sortedIDs=[19,36,58,64,69,72,77,79,80,81,82,83,84,86,87,88,91,99,102,109,110,114,115,118,120,123,124,126,128,129,132];
for(let id of sortedIDs){{ let r=buildSBU(id); if(Array.isArray(r)) ALL.push(...r); else ALL.push(r); }}

// KPI cards
let totalDaily=0,totalMTD=0,totalFY=0,totalCY=0,achList=[];
ALL.forEach(r=>{{ totalDaily+=r.daily_rev;totalMTD+=r.mtd_rev;totalFY+=r.fy_ytd_rev;totalCY+=r.cy_ytd_rev;if(r.mtd_ach_pct!=null)achList.push(r.mtd_ach_pct); }});
let avgAch=achList.length?(achList.reduce((a,b)=>a+b)/achList.length):null;
let projME=totalMTD>0?(totalMTD/DE*DM):0;
let kpiHTML='';
kpiHTML+=`<div class="kpi-card"><div class="label">Daily Revenue ({rd.strftime('%b')} {de})</div><div class="val">${{fmt(totalDaily)}} Cr</div><div class="sub">GL 3010001–3010006</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">MTD Revenue ({data['period']})</div><div class="val">${{fmt(totalMTD)}} Cr</div><div class="sub">${{DE}}/${{DM}} days (${{fmt(M_FACTOR*100,1)}}%)</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">Projected Month-End</div><div class="val">${{fmt(projME)}} Cr</div><div class="sub">Run rate: ${{fmt(totalMTD/DE)}} Cr/day</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">Avg MTD Achievement</div><div class="val">${{avgAch?fmt(avgAch,1)+'%':'N/A'}}</div><div class="sub">${{achList.length}} SBUs with targets</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">Yearly Revenue (CY YTD)</div><div class="val">${{fmt(totalCY)}} Cr</div><div class="sub">Jan 1 – {date_str}</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">YTD Revenue FY26-27</div><div class="val">${{fmt(totalFY)}} Cr</div><div class="sub">Jul 1 – {date_str}</div></div>`;
document.getElementById('kpi-row').innerHTML=kpiHTML;

// MTD bar chart
let byMTD=[...ALL].filter(r=>r.mtd_rev>0).sort((a,b)=>b.mtd_rev-a.mtd_rev).slice(0,15);
let mtdChartHTML='';
byMTD.forEach((r,i)=>{{
  let maxV=byMTD[0].mtd_rev, w=(r.mtd_rev/maxV*100).toFixed(0);
  let clr=i<3?'#38bdf8':i<6?'#818cf8':i<9?'#a78bfa':'#64748b';
  mtdChartHTML+=`<div class="bar-item"><div class="lbl">${{r.code}}</div><div class="bar-bg"><div class="bar-fill" style="width:${{w}}%;background:${{clr}}"></div></div><div class="bar-val">${{fmt(r.mtd_rev)}}</div></div>`;
}});
document.getElementById('mtd-chart').innerHTML=mtdChartHTML;

// MoM momentum
let momCats={{Strong:0,Positive:0,Neutral:0,Weak:0,Negative:0,'N/A':0}};
ALL.forEach(r=>{{ let m=r.momentum; if(!m||m==='N/A') momCats['N/A']++; else if(m.startsWith('Strong')) momCats.Strong++; else if(m==='Positive') momCats.Positive++; else if(m==='Neutral') momCats.Neutral++; else if(m==='Weak') momCats.Weak++; else momCats.Negative++; }});
let momHTML='',totalS=ALL.length;
['Strong','Positive','Neutral','Weak','Negative','N/A'].forEach(cat=>{{
  let cnt=momCats[cat], w=cnt/totalS*100;
  let clr=cat==='Strong'?'#4ade80':cat==='Positive'?'#86efac':cat==='Neutral'?'#fbbf24':cat==='Weak'?'#f97316':cat==='Negative'?'#f87171':'#64748b';
  momHTML+=`<div class="bar-item"><div class="lbl">${{cat}}</div><div class="bar-bg"><div class="bar-fill" style="width:${{w.toFixed(0)}}%;background:${{clr}}"></div></div><div class="bar-val">${{cnt}}</div></div>`;
}});
document.getElementById('mom-chart').innerHTML=momHTML;

// Insights
let top3=[...ALL].filter(r=>r.mtd_rev>0).sort((a,b)=>b.mtd_rev-a.mtd_rev).slice(0,3);
let bottom3=[...ALL].filter(r=>r.mtd_rev>0&&r.mtd_tgt_rev!=null).sort((a,b)=>a.mtd_ach_pct-b.mtd_ach_pct).slice(0,3);
let riskSBUs=[...ALL].filter(r=>(r.momentum==='Negative'||r.momentum==='Weak')&&r.mtd_rev>0);
let dormantSBUs=[...ALL].filter(r=>r.mtd_rev===0&&r.mtd_vol===0&&r.id!==64&&r.id!==79&&r.id!==80&&r.id!==81&&r.id!==88&&r.id!==110);
let snapHTML='<div class="insight-box"><h3>Snapshot</h3><ul>';
snapHTML+=`<li>Total MTD Revenue: <b>${{fmt(totalMTD)}} Cr</b> across ${{ALL.filter(r=>r.mtd_rev>0).length}} active SBUs</li>`;
snapHTML+=`<li>Daily Revenue ({rd.strftime('%b')} {de}): <b>${{fmt(totalDaily)}} Cr</b></li>`;
snapHTML+=`<li>Month Progress: <b>${{DE}}/${{DM}} (${{fmt(M_FACTOR*100,1)}}%)</b></li>`;
snapHTML+=`<li>Projected Month-End: <b>${{fmt(projME)}} Cr</b></li>`;
snapHTML+=`<li>Avg Daily Run Rate: <b>${{fmt(totalMTD/DE)}} Cr/day</b></li>`;
snapHTML+=`<li>DWH Sync: Live query at load time</li>`;
snapHTML+='</ul></div>';
let hiHTML='<div class="insight-box"><h3>SBU Highlights</h3><ul>';
top3.forEach(r=>hiHTML+=`<li class="pos">${{r.code}}: MTD ${{fmt(r.mtd_rev)}} Cr — leader (#${{top3.indexOf(r)+1}})</li>`);
hiHTML+=`<li class="pos">AAFL (109): Daily ${{fmt(GL[109]?GL[109].d:0)}} Cr — strongest performer</li>`;
hiHTML+=`<li>AEL (36): MTD ${{fmt(GL[36]?GL[36].m:0)}} Cr, FY YTD ${{fmt(GL[36]?GL[36].fy:0)}} Cr</li>`;
hiHTML+=`<li>ACCL (58): MTD ${{fmt(GL[58]?GL[58].m:0)}} Cr</li>`;
hiHTML+='</ul></div>';
let rfHTML='<div class="insight-box"><h3>Risk Flags</h3><ul>';
if(riskSBUs.length) rfHTML+=riskSBUs.map(r=>`<li class="neg">${{r.code}}: ${{r.momentum}} MoM — MTD ${{fmt(r.mtd_rev)}} Cr</li>`).join('');
else rfHTML+='<li class="pos">No SBUs in Negative/Weak momentum range</li>';
rfHTML+=`<li>ABL (124): MTD ${{fmt(GL[124]?GL[124].m:0)}} Cr — verify against portal</li>`;
rfHTML+=`<li>Orca (126): MTD ${{fmt(GL[126]?GL[126].m:0)}} Cr — verify against portal</li>`;
rfHTML+=`<li>BTL_G2G dormant since Jul 2026 — DTL_Coal (77) covers both</li>`;
if(dormantSBUs.length>0) rfHTML+=`<li>Zero-revenue SBUs: ${{dormantSBUs.map(r=>r.code).join(', ')}}</li>`;
rfHTML+='</ul></div>';
document.getElementById('insights-row').innerHTML=snapHTML+hiHTML+rfHTML;

// Reconciliation
document.getElementById('rpt-gross').textContent=fmt(RECON.rpt_gl1)+' Cr';
document.getElementById('rpt-freight').textContent=fmt(RECON.rpt_frt)+' Cr';
document.getElementById('rpt-total').textContent=fmt(RECON.rpt_tot)+' Cr';
document.getElementById('full-3010001').textContent=fmt(RECON.g1all)+' Cr';
document.getElementById('full-3010002').textContent=fmt(RECON.g2all)+' Cr';
document.getElementById('full-3010005').textContent=fmt(RECON.g5all)+' Cr';
document.getElementById('full-3010006').textContent=fmt(RECON.g6all)+' Cr';
document.getElementById('full-3010004').textContent=fmt(RECON.g4all)+' Cr';
document.getElementById('full-total').textContent=fmt(RECON.full_tot)+' Cr';
document.getElementById('recon-note').textContent='Gap: '+fmt(RECON.gap)+' Cr. Report revenue = GL 3010001–3010006 (Sales Local/Foreign, Freight, Agency). Right column includes recon-only entities (103,116,119,122,111: '+fmt(RECON.excl)+' Cr), non-report SBU entries, full-scope 3010005, and 3010004 export/other. ABL (124), Orca (126), and ALEL (114) still need portal verification.';

// Scorecard
let top3IDs=new Set([...ALL].filter(r=>r.mtd_rev>0).sort((a,b)=>b.mtd_rev-a.mtd_rev).slice(0,3).map(r=>r.id));
let SCORECARD_SORT='mtd_rev';
let SCORECARD_FILTER='';
function renderScorecard(){{
  let sorted=[...ALL];
  let sortBy=SCORECARD_SORT;
  if(sortBy==='mtd_rev'||sortBy==='daily_rev'||sortBy==='proj_rev') sorted.sort((a,b)=>b[sortBy]-a[sortBy]);
  else if(sortBy==='code') sorted.sort((a,b)=>a.code.localeCompare(b.code));
  else sorted.sort((a,b)=>(b[sortBy]||0)-(a[sortBy]||0));
  if(SCORECARD_FILTER){{ let q=SCORECARD_FILTER.toLowerCase(); sorted=sorted.filter(r=>r.code.toLowerCase().includes(q)); }}
  let tbodyHTML='';
  sorted.forEach((r,origIdx)=>{{
    let dodPct=r.dod_rev>0?pct(r.daily_rev,r.dod_rev):null;
    let topCls=top3IDs.has(r.id)?' top-performer':'',idx=ALL.indexOf(r);
    tbodyHTML+=`<tr class="sbu-row${{topCls}}" data-idx="${{idx}}" data-sbu="${{r.id}}">
<td>${{r.code}} <span style="font-size:0.85rem;color:#94a3b8">${{r.src}}</span> <span class="chart-toggle" data-idx="${{idx}}">&#9654;</span></td>
<td class="num">${{fmt(r.daily_rev)}}</td>
<td class="num ${{dodPct!=null&&dodPct>=0?'mom-up':dodPct!=null?'mom-down':''}}">${{dodPct!=null?fmt(dodPct,1)+'%':'—'}}</td>
<td class="num">${{fmt(r.mtd_rev)}}</td>
<td class="num">${{r.mtd_tgt_rev!=null?fmt(r.mtd_tgt_rev):'—'}}</td>
<td class="num ${{r.mtd_ach_pct!=null&&r.mtd_ach_pct>=100?'mom-up':r.mtd_ach_pct!=null&&r.mtd_ach_pct<50?'mom-down':''}}">${{r.mtd_ach_pct!=null?fmt(r.mtd_ach_pct,1)+'%':'—'}}</td>
<td class="num ${{r.mom_pct!=null&&r.mom_pct>0?'mom-up':r.mom_pct!=null?'mom-down':''}}">${{r.mom_pct!=null?fmt(r.mom_pct,1)+'%':'—'}}</td>
<td class="num">${{r.yoy_pct!=null?fmt(r.yoy_pct,1)+'%':'—'}}</td>
<td class="num">${{fmt(r.fy_ytd_rev)}}</td>
<td class="num">${{fmt(r.cy_ytd_rev)}}</td>
<td class="num">${{fmt(r.proj_rev)}}</td>
<td class="${{momCls(r.mom_pct)}}">${{r.momentum}}</td>
<td class="num vol-cell">${{r.has_vol&&r.mtd_vol!=null?fmt(r.mtd_vol,1):'—'}}</td>
<td class="num vol-cell">${{r.has_vol&&r.daily_vol!=null?fmt(r.daily_vol,1):'—'}}</td>
<td></td></tr>
<tr class="chart-row" id="cr-${{idx}}"><td colspan="15"><div class="chart-canvas-wrap"><canvas id="c${{idx}}" width="560" height="200"></canvas></div></td></tr>`;
  }});
  document.getElementById('scorecard-body').innerHTML=tbodyHTML;
  // Re-bind chart toggle handlers
  document.querySelectorAll('.chart-toggle').forEach(el=>{{
    el.addEventListener('click',function(e){{ e.stopPropagation(); let idx=this.dataset.idx; let row=document.getElementById('cr-'+idx); let isOpen=row.classList.contains('open'); row.classList.toggle('open'); this.classList.toggle('open'); if(!isOpen) drawSBUChart(idx); }});
  }});
  document.querySelectorAll('.sbu-row').forEach(el=>{{
    el.addEventListener('click',function(){{ let toggle=this.querySelector('.chart-toggle'); if(toggle) toggle.click(); }});
  }});
}}
renderScorecard();
function sortScorecard(){{ SCORECARD_SORT=document.getElementById('scorecard-sort').value; renderScorecard(); }}
function filterScorecard(){{ SCORECARD_FILTER=document.getElementById('scorecard-filter').value; renderScorecard(); }}

// === CHART FUNCTIONS ===
function drawAxes(ctx,w,h,pad,ymax,xlabels,ylabel){{
  ctx.strokeStyle='#334155';ctx.lineWidth=0.5;ctx.fillStyle='#94a3b8';ctx.font='11px monospace';
  let cW=w-pad.left-pad.right,cH=h-pad.top-pad.bottom,ysteps=5;
  for(let i=0;i<=ysteps;i++){{ let y=pad.top+(cH/ysteps*i);ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(w-pad.right,y);ctx.stroke();ctx.fillText(fmt(ymax-(ymax/ysteps*i),1),2,y+3); }}
  xlabels.forEach((l,i)=>{{ ctx.fillText(l,pad.left+(cW/(xlabels.length-1)*i)-8,h-2); }});
  if(ylabel){{ ctx.save();ctx.translate(8,pad.top+cH/2);ctx.rotate(-Math.PI/2);ctx.fillText(ylabel,-ctx.measureText(ylabel).width/2,0);ctx.restore(); }}
}}

function drawPortfolioDaily(){{
  let c=document.getElementById('portfolio-daily');if(!c)return;
  let ctx=c.getContext('2d'),w=c.width,h=c.height,pad={{top:25,right:30,bottom:25,left:50}};
  let dtMap={{}};TD.forEach(t=>{{dtMap[t.d]=(dtMap[t.d]||0)+t.v;}});
  let dates=Object.keys(dtMap).sort(),vals=dates.map(d=>dtMap[d]);
  let ymax=Math.max(...vals)*1.2;
  let cW=w-pad.left-pad.right,cH=h-pad.top-pad.bottom;
  drawAxes(ctx,w,h,pad,ymax,dates.map(d=>d.slice(8)),'Cr');
  let barGap=4,barW=Math.max(6,cW/dates.length-barGap);
  let bars=[]; // store for hover
  vals.forEach((v,i)=>{{
    let x=pad.left+(cW/(vals.length-1)*i)-barW/2,hb=(v/ymax*cH);
    let grad=ctx.createLinearGradient(0,pad.top+cH-hb,0,pad.top+cH);
    grad.addColorStop(0,'#38bdf8');grad.addColorStop(1,'#1d4ed8');
    ctx.fillStyle=grad;ctx.fillRect(x,pad.top+cH-hb,barW,hb);
    ctx.fillStyle='#e2e8f0';ctx.font='10px monospace';ctx.fillText(fmt(v,2),x-4,pad.top+cH-hb-2);
    bars.push({{x:x, w:barW, v:v, d:dates[i]}});
  }});
  let cum=0,cumVals=vals.map(v=>cum+=v);
  ctx.strokeStyle='#fbbf24';ctx.lineWidth=2;ctx.setLineDash([4,3]);ctx.beginPath();
  cumVals.forEach((cv,i)=>{{ let x=pad.left+(cW/(cumVals.length-1)*i),y=pad.top+cH-(cv/Math.max(...cumVals)*1.1*cH);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y); }});
  ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle='#fbbf24';ctx.font='10px monospace';ctx.fillText('MTD:'+fmt(cum,2),pad.left+cW-55,pad.top+10);
  // Summary stats
  let avgDaily=vals.reduce((a,b)=>a+b,0)/vals.length,peakDay=dates[vals.indexOf(Math.max(...vals))];
  let trendDir='Stable',firstHalf=vals.slice(0,Math.floor(vals.length/2)).reduce((a,b)=>a+b,0);
  let secondHalf=vals.slice(Math.ceil(vals.length/2)).reduce((a,b)=>a+b,0);
  if(secondHalf>firstHalf*1.1) trendDir='Rising \u2191'; else if(firstHalf>secondHalf*1.1) trendDir='Dipping \u2193';
  document.getElementById('portfolio-stats').innerHTML=`<span>Avg Daily: <b>${{fmt(avgDaily)}} Cr</b></span><span>Peak: <b>${{peakDay.slice(5)}} (${{fmt(Math.max(...vals))}} Cr)</b></span><span>Trend: <b>${{trendDir}}</b></span><span>Range: <b>${{fmt(Math.min(...vals))}}–${{fmt(Math.max(...vals))}} Cr</b></span>`;
  // Hover tooltip
  let tip=document.createElement('div');tip.id='pd-tip';tip.style.cssText='position:absolute;display:none;background:#0f172a;color:#e2e8f0;padding:4px 8px;border-radius:4px;font-size:13px;pointer-events:none;border:1px solid #38bdf8;white-space:nowrap;z-index:99';
  let wrap=c.parentElement;if(wrap.style.position!=='relative') wrap.style.position='relative';wrap.appendChild(tip);
  let oldHover=null;
  c.onmousemove=function(e){{
    let rect=c.getBoundingClientRect(),mx=e.clientX-rect.left,my=e.clientY-rect.top;
    let found=null;
    bars.forEach(b=>{{if(mx>=b.x&&mx<=b.x+b.w&&my>=pad.top&&my<=pad.top+cH)found=b;}});
    if(found){{
      tip.style.display='block';tip.style.left=(e.clientX-rect.left+12)+'px';tip.style.top=(e.clientY-rect.top-22)+'px';
      tip.textContent=found.d.slice(5)+': '+fmt(found.v,2)+' Cr';
      if(oldHover!==found){{ c.style.cursor='pointer'; oldHover=found; }}
    }}else{{ tip.style.display='none';oldHover=null;c.style.cursor='crosshair'; }}
  }};
  c.onmouseleave=function(){{ tip.style.display='none';oldHover=null; }};
}}

function drawTop5Stacked(){{
  let c=document.getElementById('top5-stacked');if(!c)return;
  let ctx=c.getContext('2d'),w=c.width,h=c.height,pad={{top:25,right:20,bottom:25,left:45}};
  ctx.clearRect(0,0,w,h);
  let byMTD=[...ALL].filter(r=>r.mtd_rev>0).sort((a,b)=>b.mtd_rev-a.mtd_rev).slice(0,5);
  let colors=['#38bdf8','#818cf8','#c084fc','#f472b6','#fbbf24'];
  let dates=[...new Set(TD.map(t=>t.d))].sort();
  let cW=w-pad.left-pad.right,cH=h-pad.top-pad.bottom;
  let maxStack=0;
  dates.forEach(d=>{{ let stack=byMTD.reduce((s,r)=>s+(TD.filter(t=>t.d===d&&t.s===r.id).reduce((a,b)=>a+b.v,0)),0);maxStack=Math.max(maxStack,stack); }});
  maxStack*=1.15;
  drawAxes(ctx,w,h,pad,maxStack,dates.map(d=>d.slice(8)),'Cr');
  byMTD.forEach((r,i)=>{{ ctx.fillStyle=colors[i];ctx.fillRect(w-130,8+i*14,10,10);ctx.fillStyle='#e2e8f0';ctx.font='11px sans-serif';ctx.fillText(r.code,w-116,17+i*14); }});
  let barGap=3,barW=Math.max(8,cW/dates.length-barGap);
  let segments=[]; // store for hover
  dates.forEach((d,di)=>{{
    let x=pad.left+(cW/(dates.length-1)*di)-barW/2,sy=pad.top+cH;
    byMTD.forEach((r,si)=>{{ let v=TD.filter(t=>t.d===d&&t.s===r.id).reduce((a,b)=>a+b.v,0);sy-=(v/maxStack*cH);ctx.fillStyle=colors[si];ctx.fillRect(x,sy,barW,v/maxStack*cH);segments.push({{x:x,w:barW,t:sy,h:v/maxStack*cH,sbu:r.code,v:v,di:di,si:si}}); }});
  }});
  // Hover tooltip
  let tip=document.createElement('div');tip.id='t5-tip';tip.style.cssText='position:absolute;display:none;background:#0f172a;color:#e2e8f0;padding:4px 8px;border-radius:4px;font-size:13px;pointer-events:none;border:1px solid #38bdf8;white-space:nowrap;z-index:99';
  let wrap=c.parentElement;if(wrap.style.position!=='relative') wrap.style.position='relative';wrap.appendChild(tip);
  c.onmousemove=function(e){{
    let rect=c.getBoundingClientRect(),mx=e.clientX-rect.left,my=e.clientY-rect.top;
    let found=segments.filter(s=>mx>=s.x&&mx<=s.x+s.w&&my>=s.t&&my<=s.t+s.h).pop();
    if(found){{
      tip.style.display='block';tip.style.left=(e.clientX-rect.left+12)+'px';tip.style.top=(e.clientY-rect.top-22)+'px';
      tip.textContent=found.sbu+': '+fmt(found.v,2)+' Cr';
      c.style.cursor='pointer';
    }}else{{ tip.style.display='none';c.style.cursor='crosshair'; }}
  }};
  c.onmouseleave=function(){{ tip.style.display='none'; }};
}}

function drawSBUChart(idx){{
  let r=ALL[idx],c=document.getElementById('c'+idx);if(!c||!r)return;
  let ctx=c.getContext('2d'),w=c.width,h=c.height,pad={{top:20,right:30,bottom:22,left:50}};
  ctx.clearRect(0,0,w,h);
  let days=TD.filter(t=>t.s===r.id);
  if(!days.length){{ctx.fillStyle='#64748b';ctx.font='13px sans-serif';ctx.fillText('No daily data for '+r.code,20,40);return;}}
  let dates=[...new Set(days.map(t=>t.d))].sort(),vals=dates.map(d=>days.filter(t=>t.d===d).reduce((a,b)=>a+b.v,0));
  let ymax=Math.max(...vals)*1.3||1,cW=w-pad.left-pad.right,cH=h-pad.top-pad.bottom;
  ctx.fillStyle='#f8fafc';ctx.font='bold 13px sans-serif';ctx.fillText(r.code+' Daily Revenue Trend (Cr) — Click bars for values',pad.left,pad.top-5);
  drawAxes(ctx,w,h,pad,ymax,dates.map(d=>d.slice(8)),'');
  let barGap=3,barW=Math.max(8,cW/dates.length-barGap);
  let sbuBars=[];
  let palette=['#38bdf8','#818cf8','#c084fc','#f472b6','#fbbf24','#4ade80','#fb923c'];
  vals.forEach((v,i)=>{{ let x=pad.left+(cW/(vals.length-1)*i)-barW/2,hb=(v/ymax*cH);let clr=palette[i%palette.length];ctx.fillStyle=i===vals.length-1?'#38bdf8':clr;ctx.fillRect(x,pad.top+cH-hb,barW,hb);ctx.fillStyle='#e2e8f0';ctx.font='10px monospace';ctx.fillText(fmt(v,2),x-3,pad.top+cH-hb-2);sbuBars.push({{x:x,w:barW,v:v,d:dates[i]}}); }});
  let cum=0,cumVals=vals.map(v=>cum+=v);
  ctx.strokeStyle='#fbbf24';ctx.lineWidth=2;ctx.setLineDash([4,3]);ctx.beginPath();
  cumVals.forEach((cv,i)=>{{ ctx.lineTo(pad.left+(cW/(cumVals.length-1)*i),pad.top+cH-(cv/Math.max(...cumVals)*1.15*cH)); }});
  ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#fbbf24';ctx.font='10px monospace';ctx.fillText('MTD:'+fmt(cum,2),pad.left+cW-55,pad.top+10);
  if(r.mtd_tgt_rev!=null){{ let tY=pad.top+cH-((r.mtd_tgt_rev/DE)/ymax*cH);ctx.strokeStyle='#f87171';ctx.lineWidth=1;ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(pad.left,tY);ctx.lineTo(pad.left+cW,tY);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#f87171';ctx.font='10px monospace';ctx.fillText('Tgt/day:'+fmt(r.mtd_tgt_rev/DE,2),pad.left,tY-3); }}
  // Click to show value
  c.onclick=function(e){{
    let rect=c.getBoundingClientRect(),mx=e.clientX-rect.left,my=e.clientY-rect.top;
    let found=sbuBars.find(b=>mx>=b.x&&mx<=b.x+b.w&&my>=pad.top&&my<=pad.top+cH);
    if(found){{ let old=c.dataset.selected; if(old==found.d){{ delete c.dataset.selected;ctx.clearRect(0,0,w,h);drawSBUChart(idx);return; }}
      c.dataset.selected=found.d;ctx.save();ctx.fillStyle='#fbbf24';ctx.font='bold 11px sans-serif';
      ctx.fillText(found.d.slice(5)+': '+fmt(found.v,2)+' Cr',found.x+found.w/2-30,pad.top+cH-(found.v/ymax*cH)-10);ctx.restore();
    }}
  }};
}}

window.addEventListener('load',function(){{ drawPortfolioDaily(); drawTop5Stacked(); document.getElementById('loading-overlay').classList.add('hidden'); }});
</script>
</body>
</html>'''


class LiveHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0].rstrip('/')

        if path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            import json as _json
            try:
                conn = get_conn()
                c = conn.cursor()
                c.execute("SELECT 1")
                conn.close()
                self.wfile.write(_json.dumps({"status":"ok","db":"connected"}).encode())
            except Exception as e:
                self.wfile.write(_json.dumps({"status":"error","db":str(e)}).encode())
            return

        if path in ('', '/', '/report'):
            try:
                rd = detect_report_date()
                data = get_report_data(rd)
                html = build_html(data)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            except Exception as e:
                import traceback
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                err = traceback.format_exc()
                self.wfile.write(err.encode())
                print(f"ERROR: {e}", flush=True)
            return

        # Serve static files
        if path.startswith('/'):
            path = path[1:]
        file_path = ROOT / (path or 'index.html')
        if file_path.exists() and file_path.suffix in ('.html', '.js', '.css', '.ico'):
            self.send_response(200)
            ct = 'text/html' if file_path.suffix == '.html' else 'text/javascript' if file_path.suffix == '.js' else 'text/css'
            self.send_header('Content-Type', ct)
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
            return

        return super().do_GET()

    def log_message(self, fmt, *args):
        print(f'[{datetime.now().strftime("%H:%M:%S")}] {args[0]}', flush=True)


class ThreadedHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    """Handle requests in separate threads so a slow DWH query doesn't block other requests."""
    daemon_threads = True

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', PORT)))
    ap.add_argument('--host', default=os.environ.get('HOST', HOST))
    ap.add_argument('--no-browser', action='store_true')
    args = ap.parse_args()
    PORT, HOST = args.port, args.host

    os.chdir(str(ROOT))
    server = ThreadedHTTPServer((HOST, PORT), LiveHandler)
    url = f'http://{HOST}:{PORT}'
    print(f'ARL Live Flash Report running at {url}', flush=True)
    print('Auto-detects T-1 date · Fresh DWH queries on every load', flush=True)
    print('Press Ctrl+C to stop', flush=True)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down...')
        server.shutdown()
