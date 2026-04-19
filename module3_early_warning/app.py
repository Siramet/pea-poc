import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
from datetime import datetime
from fastapi import FastAPI
from pydantic import BaseModel
from shared.synthetic_data import get_site_config

app = FastAPI(title="PEA Early Warning API", version="1.0.0")
CONFIG = get_site_config()

RULES = {
    "load_peak_warning":  CONFIG["load_peak_kw"] * 0.80,
    "load_peak_critical": CONFIG["load_peak_kw"] * 0.92,
    "pv_drop_warning":    CONFIG["pv_capacity_kw"] * 0.30,
    "bess_low_warning":   30.0,
    "bess_low_critical":  22.0,
    "bess_high_warning":  85.0,
    "ramp_rate_kw_hr":    50.0,
}

def check_alerts(forecast, bess_soc=60.0):
    alerts = []
    loads = [f["load_kw"] for f in forecast]
    pvs   = [f["pv_kw"]   for f in forecast]
    dts   = [f["datetime"] for f in forecast]
    for i, (lkw, dt) in enumerate(zip(loads, dts)):
        if lkw >= RULES["load_peak_critical"]:
            alerts.append({"level":"critical","code":"LOAD_PEAK_CRITICAL",
                "message":f"Load {lkw:.0f} kW เกิน 92% ของ peak","at_datetime":dt,
                "recommendation":"Discharge BESS + เตรียม Diesel ทันที"})
        elif lkw >= RULES["load_peak_warning"]:
            alerts.append({"level":"warning","code":"LOAD_PEAK_WARNING",
                "message":f"Load {lkw:.0f} kW เกิน 80% ของ peak","at_datetime":dt,
                "recommendation":"เตรียม BESS Discharge"})
    daytime = [(pv,dt) for pv,dt in zip(pvs,dts) if 7 <= pd.Timestamp(dt).hour <= 17]
    for pv, dt in daytime:
        if pv < RULES["pv_drop_warning"]:
            alerts.append({"level":"warning","code":"PV_DROP",
                "message":f"PV ลดเหลือ {pv:.0f} kW ช่วงกลางวัน","at_datetime":dt,
                "recommendation":"เตรียม Grid import ชดเชย"})
    if bess_soc <= RULES["bess_low_critical"]:
        alerts.append({"level":"critical","code":"BESS_SOC_CRITICAL",
            "message":f"BESS SOC ต่ำมาก ({bess_soc:.0f}%)",
            "recommendation":"หยุด Discharge ทันที"})
    elif bess_soc <= RULES["bess_low_warning"]:
        alerts.append({"level":"warning","code":"BESS_SOC_LOW",
            "message":f"BESS SOC ต่ำ ({bess_soc:.0f}%)",
            "recommendation":"Charge จาก Grid ช่วง Off-peak"})
    if bess_soc >= RULES["bess_high_warning"]:
        alerts.append({"level":"warning","code":"BESS_SOC_HIGH",
            "message":f"BESS SOC สูง ({bess_soc:.0f}%)",
            "recommendation":"หยุด Charge"})
    for i in range(1, len(loads)):
        ramp = abs(loads[i] - loads[i-1])
        if ramp >= RULES["ramp_rate_kw_hr"]:
            alerts.append({"level":"info","code":"LOAD_RAMP",
                "message":f"Load เปลี่ยนเร็ว {ramp:.0f} kW/hr","at_datetime":dts[i],
                "recommendation":"BESS รองรับได้ทันที"})
    alerts.sort(key=lambda a: {"critical":0,"warning":1,"info":2}[a["level"]])
    return alerts[:20]

def build_response(alerts):
    has_critical = any(a["level"]=="critical" for a in alerts)
    n_critical   = sum(1 for a in alerts if a["level"]=="critical")
    n_warning    = sum(1 for a in alerts if a["level"]=="warning")
    if has_critical:
        summary = f"CRITICAL: {n_critical} alert ต้องดำเนินการทันที"
    elif n_warning:
        summary = f"WARNING: {n_warning} alert ควรเตรียมแผนรับมือ"
    else:
        summary = "OK: ระบบปกติ ไม่มี alert ใน 24h"
    return {"checked_at":datetime.now().isoformat(),
            "alert_count":len(alerts),"has_critical":has_critical,
            "alerts":alerts,"summary":summary}

@app.get("/alerts/health")
def health():
    return {"status":"ok","rules_count":len(RULES)}

@app.get("/alerts/now")
def alerts_now(bess_soc: float = 60.0):
    from shared.synthetic_data import generate_load, generate_pv
    now = pd.Timestamp.now().floor("h")
    load_df = generate_load(str(now.date()), 24)
    pv_df   = generate_pv(str(now.date()), 24)
    forecast = [{"datetime":str(load_df["ds"].iloc[i]),
                 "load_kw":round(float(load_df["y"].iloc[i]),1),
                 "pv_kw":round(float(pv_df["y"].iloc[i]),1),
                 "net_kw":round(float(load_df["y"].iloc[i]-pv_df["y"].iloc[i]),1)}
                for i in range(24)]
    return build_response(check_alerts(forecast, bess_soc))
