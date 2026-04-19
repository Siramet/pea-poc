import streamlit as st
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

st.set_page_config(page_title="PEA Energy Dashboard", layout="wide", page_icon="⚡")

from shared.synthetic_data import generate_load, generate_pv, get_site_config

CONFIG = get_site_config()
COSTS  = CONFIG["costs"]

@st.cache_data
def get_forecast(start_date):
    load_df = generate_load(str(start_date), 24)
    pv_df   = generate_pv(str(start_date), 24)
    rows = []
    for i in range(24):
        rows.append({
            "datetime": load_df["ds"].iloc[i],
            "hour": load_df["ds"].iloc[i].hour,
            "load_kw": round(float(load_df["y"].iloc[i]), 1),
            "pv_kw":   round(float(pv_df["y"].iloc[i]), 1),
        })
    df = pd.DataFrame(rows)
    df["net_kw"] = (df["load_kw"] - df["pv_kw"]).round(1)
    return df

def dispatch(df, strategy, bess_soc_init=60.0):
    soc = bess_soc_init / 100
    cap = CONFIG["bess_capacity_kwh"]
    p_max = CONFIG["bess_power_kw"]
    soc_min, soc_max = 0.20, 0.90
    rows = []
    for _, r in df.iterrows():
        load = r["load_kw"]
        pv   = min(r["pv_kw"], load)
        remain = load - pv
        bess_d = bess_c = 0.0
        if strategy in ["cost_minimize", "green_first"]:
            if soc > soc_min + 0.05:
                bess_d  = min(remain, p_max, (soc - soc_min) * cap)
                remain -= bess_d
                soc    -= bess_d / cap
        grid   = min(remain, CONFIG["grid_max_kw"])
        remain -= grid
        diesel = max(0, remain)
        h = r["hour"]
        if h in list(range(0, 6)) + [23] and strategy != "bess_protect":
            if soc < soc_max - 0.05:
                bess_c = min(p_max, (soc_max - soc) * cap)
                soc   += bess_c / cap
        gc   = COSTS["grid_peak_thb_kwh"] if 9 <= h <= 21 else COSTS["grid_offpeak_thb_kwh"]
        dc   = COSTS["diesel_thb_liter"] * COSTS["diesel_liter_per_kwh"]
        cost = grid * gc + diesel * dc
        rows.append({
            "hour": h, "load_kw": load, "pv_kw": round(pv,1),
            "grid_kw": round(grid,1), "bess_kw": round(bess_d-bess_c,1),
            "diesel_kw": round(diesel,1), "bess_soc_pct": round(soc*100,1),
            "cost_thb": round(cost,2),
        })
    return pd.DataFrame(rows)

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚡ PEA Energy POC")
    st.caption("Challenge #4 — Energy Optimization")
    st.divider()
    selected_date = st.date_input("วันที่", value=pd.Timestamp("2024-06-15"))
    strategy = st.selectbox("กลยุทธ์", ["cost_minimize","bess_protect","green_first"],
        format_func=lambda x: {"cost_minimize":"A — Cost Minimize",
                                "bess_protect": "B — BESS Protect",
                                "green_first":  "C — Green First"}[x])
    bess_soc = st.slider("BESS SOC เริ่มต้น (%)", 20, 90, 60)
    st.divider()
    st.caption(f"PV Capacity: {CONFIG['pv_capacity_kw']} kW")
    st.caption(f"BESS: {CONFIG['bess_capacity_kwh']} kWh")
    st.caption(f"Diesel: {CONFIG['diesel_rated_kw']} kW")

# ── Data ───────────────────────────────────────────────────────────────────
forecast_df = get_forecast(selected_date)
schedule_df = dispatch(forecast_df, strategy, bess_soc)

# ── Header ─────────────────────────────────────────────────────────────────
st.title("PEA Energy Resource Dashboard")
st.caption(f"วันที่ {selected_date} | กลยุทธ์: {strategy.replace('_',' ').title()}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Peak Load", f"{schedule_df['load_kw'].max():.0f} kW")
c2.metric("PV รวม", f"{schedule_df['pv_kw'].sum():.0f} kWh")
c3.metric("ค่าไฟรวม", f"฿{schedule_df['cost_thb'].sum():,.0f}")
c4.metric("Diesel", f"{schedule_df['diesel_kw'].sum()*COSTS['diesel_liter_per_kwh']:.0f} L")

st.divider()

# ── Dispatch Chart ─────────────────────────────────────────────────────────
st.subheader("Dispatch Schedule 24 ชั่วโมง")
chart_df = schedule_df[["hour","pv_kw","bess_kw","grid_kw","diesel_kw"]].set_index("hour")
chart_df.columns = ["PV Solar","BESS","Main Grid","Diesel"]
st.bar_chart(chart_df, color=["#F59E0B","#10B981","#3B82F6","#EF4444"])

# ── Source Mix ─────────────────────────────────────────────────────────────
st.subheader("Source Mix รวม 24h")
total_pv     = schedule_df["pv_kw"].clip(lower=0).sum()
total_bess   = schedule_df["bess_kw"].clip(lower=0).sum()
total_grid   = schedule_df["grid_kw"].sum()
total_diesel = schedule_df["diesel_kw"].sum()
total_all    = total_pv + total_bess + total_grid + total_diesel

m1, m2, m3, m4 = st.columns(4)
m1.metric("PV Solar",  f"{total_pv/total_all*100:.1f}%",  f"{total_pv:.0f} kWh")
m2.metric("BESS",      f"{total_bess/total_all*100:.1f}%", f"{total_bess:.0f} kWh")
m3.metric("Main Grid", f"{total_grid/total_all*100:.1f}%", f"{total_grid:.0f} kWh")
m4.metric("Diesel",    f"{total_diesel/total_all*100:.1f}%",f"{total_diesel:.0f} kWh")

st.divider()

# ── BESS SOC ───────────────────────────────────────────────────────────────
st.subheader("BESS State of Charge (%)")
st.line_chart(schedule_df[["hour","bess_soc_pct"]].set_index("hour"), color=["#10B981"])

st.divider()

# ── Early Warning ──────────────────────────────────────────────────────────
st.subheader("Early Warning")
alerts = []
for _, r in schedule_df.iterrows():
    if r["load_kw"] >= CONFIG["load_peak_kw"] * 0.92:
        alerts.append(("critical", f"Hour {r['hour']:02d}:00 — Load {r['load_kw']:.0f} kW เกิน 92% ของ peak"))
    elif r["load_kw"] >= CONFIG["load_peak_kw"] * 0.80:
        alerts.append(("warning",  f"Hour {r['hour']:02d}:00 — Load {r['load_kw']:.0f} kW เกิน 80% ของ peak"))
    if r["diesel_kw"] > 0:
        alerts.append(("warning",  f"Hour {r['hour']:02d}:00 — Diesel ทำงาน {r['diesel_kw']:.0f} kW"))

if not alerts:
    st.success("✅ ระบบปกติ — ไม่มี alert ใน 24h")
else:
    for level, msg in alerts[:8]:
        if level == "critical":
            st.error(f"⛔ {msg}")
        else:
            st.warning(f"⚠️ {msg}")

st.divider()

# ── Table ──────────────────────────────────────────────────────────────────
with st.expander("ดู Dispatch Schedule ทั้งหมด"):
    st.dataframe(schedule_df.set_index("hour"), use_container_width=True)
