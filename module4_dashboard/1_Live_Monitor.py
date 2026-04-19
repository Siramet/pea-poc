import streamlit as st
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

st.set_page_config(page_title="PEA Live Monitor", layout="wide", page_icon="⚡")

from shared.synthetic_data import generate_load, generate_pv, get_site_config
from module2_optimization.app import rule_dispatch, COSTS
from module3_early_warning.app import check_alerts

CONFIG = get_site_config()

with st.sidebar:
    st.title("⚡ PEA Energy POC")
    st.caption("Challenge #4 — Energy Optimization")
    st.divider()
    selected_date = st.date_input("วันที่", value=pd.Timestamp("2024-06-15"))
    strategy = st.selectbox("กลยุทธ์",
        ["cost_minimize","bess_protect","green_first"],
        format_func=lambda x: {"cost_minimize":"A — Cost Minimize",
                                "bess_protect": "B — BESS Protect",
                                "green_first":  "C — Green First"}[x])
    bess_soc = st.slider("BESS SOC เริ่มต้น (%)", 20, 90, 60)
    st.divider()
    st.caption(f"PV: {CONFIG['pv_capacity_kw']} kW")
    st.caption(f"BESS: {CONFIG['bess_capacity_kwh']} kWh")
    st.caption(f"Diesel: {CONFIG['diesel_rated_kw']} kW")

@st.cache_data
def get_data(date, strat, soc):
    load_df = generate_load(str(date), 24)
    pv_df   = generate_pv(str(date), 24)
    fc = [{"datetime": str(load_df["ds"].iloc[i]),
            "load_kw":  round(float(load_df["y"].iloc[i]), 1),
            "pv_kw":    round(float(pv_df["y"].iloc[i]), 1),
            "net_kw":   round(float(load_df["y"].iloc[i] - pv_df["y"].iloc[i]), 1)}
           for i in range(24)]
    sch = rule_dispatch(fc, soc, strat)
    sdf = pd.DataFrame(sch)
    if "hour" not in sdf.columns:
        sdf["hour"] = pd.to_datetime(sdf["datetime"]).dt.hour
    return fc, sdf

fc, sdf = get_data(selected_date, strategy, bess_soc)

st.title("⚡ PEA Live Energy Monitor")
st.caption(f"วันที่ {selected_date} | กลยุทธ์: {strategy.replace('_',' ').title()}")

peak_load  = sdf["load_kw"].max()
total_pv   = sdf["pv_kw"].clip(lower=0).sum()
total_cost = sdf["cost_thb"].sum()
diesel_L   = sdf["diesel_kw"].sum() * COSTS["diesel_liter_per_kwh"]
current_soc= sdf["bess_soc_pct"].iloc[-1]
peak_hour  = sdf.loc[sdf["load_kw"].idxmax(), "hour"]

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Peak Load",    f"{peak_load:.0f} kW",   f"Hour {peak_hour:02d}:00")
c2.metric("PV ผลิตได้",   f"{total_pv:.0f} kWh",  f"{total_pv/sdf['load_kw'].sum()*100:.0f}%")
c3.metric("ค่าไฟรวม",     f"฿{total_cost:,.0f}")
c4.metric("Diesel ใช้",   f"{diesel_L:.0f} L")
c5.metric("BESS SOC สิ้นวัน", f"{current_soc:.0f}%",
          delta="ดี" if current_soc >= 40 else "ต่ำ",
          delta_color="normal" if current_soc >= 40 else "inverse")

st.divider()

alerts = check_alerts(fc, bess_soc)
n_critical = sum(1 for a in alerts if a["level"] == "critical")
n_warning  = sum(1 for a in alerts if a["level"] == "warning")

if n_critical > 0:
    st.error(f"⛔ {n_critical} CRITICAL ALERT — ต้องดำเนินการทันที")
elif n_warning > 0:
    st.warning(f"⚠️ {n_warning} Warning — ควรเตรียมแผนรับมือ")
else:
    st.success("✅ ระบบปกติ — ไม่มี alert ใน 24h")

if alerts:
    with st.expander(f"ดู alerts ทั้งหมด ({len(alerts)} รายการ)"):
        for a in alerts[:10]:
            if a["level"] == "critical":
                st.error(f"⛔ {a['message']} — {a['recommendation']}")
            elif a["level"] == "warning":
                st.warning(f"⚠️ {a['message']} — {a['recommendation']}")
            else:
                st.info(f"ℹ️ {a['message']} — {a['recommendation']}")

st.divider()
st.subheader("Energy Flow — Dispatch Schedule 24h")

col_chart, col_mix = st.columns([2,1])
with col_chart:
    chart_df = sdf[["hour","pv_kw","bess_kw","grid_kw","diesel_kw"]].set_index("hour")
    chart_df.columns = ["PV Solar","BESS","Main Grid","Diesel"]
    st.bar_chart(chart_df, color=["#F59E0B","#10B981","#3B82F6","#EF4444"])
with col_mix:
    total_bess   = sdf["bess_kw"].clip(lower=0).sum()
    total_grid   = sdf["grid_kw"].sum()
    total_diesel = sdf["diesel_kw"].sum()
    total_all    = total_pv+total_bess+total_grid+total_diesel
    mx1,mx2 = st.columns(2)
    mx1.metric("PV",   f"{total_pv/total_all*100:.1f}%",   f"{total_pv:.0f} kWh")
    mx2.metric("BESS", f"{total_bess/total_all*100:.1f}%",  f"{total_bess:.0f} kWh")
    mx3,mx4 = st.columns(2)
    mx3.metric("Grid",   f"{total_grid/total_all*100:.1f}%",   f"{total_grid:.0f} kWh")
    mx4.metric("Diesel", f"{total_diesel/total_all*100:.1f}%", f"{total_diesel:.0f} kWh")

st.divider()
st.subheader("BESS State of Charge")
col_soc, col_info = st.columns([3,1])
with col_soc:
    st.line_chart(sdf[["hour","bess_soc_pct"]].set_index("hour"), color=["#10B981"])
with col_info:
    min_soc = sdf["bess_soc_pct"].min()
    max_soc = sdf["bess_soc_pct"].max()
    st.metric("SOC ต่ำสุด", f"{min_soc:.0f}%",
              delta="OK" if min_soc>=20 else "ต่ำเกิน!",
              delta_color="normal" if min_soc>=20 else "inverse")
    st.metric("SOC สูงสุด", f"{max_soc:.0f}%")
    st.metric("SOC สิ้นวัน", f"{current_soc:.0f}%")

st.divider()
st.subheader("คำแนะนำ Operator รายชั่วโมง")

def get_action(row):
    h,load = int(row["hour"]),row["load_kw"]
    pv,bess = row["pv_kw"],row["bess_kw"]
    grid,soc = row["grid_kw"],row["bess_soc_pct"]
    diesel = row["diesel_kw"]
    total = load if load>0 else 1
    sources = []
    if pv>0:     sources.append(f"PV {pv:.0f}kW")
    if bess>0:   sources.append(f"BESS {bess:.0f}kW")
    if grid>0:   sources.append(f"Grid {grid:.0f}kW")
    if diesel>0: sources.append(f"Diesel {diesel:.0f}kW")
    mix = " + ".join(sources) or "Grid only"
    actions = []
    if 0<=h<=5:   actions.append("Off-peak: Charge BESS จาก Grid ราคาถูก")
    if 6<=h<=8:   actions.append("PV เริ่มขึ้น: ลด Grid import")
    if 9<=h<=16 and pv>load*0.5: actions.append("PV แรง: ใช้ PV เป็นหลัก")
    if 17<=h<=20: actions.append("PV ลด: Discharge BESS ชดเชย")
    if 21<=h<=23: actions.append("กลางคืน: Grid Off-peak ประหยัด")
    if load>=CONFIG["load_peak_kw"]*0.80: actions.append("⚠️ Load สูง")
    if soc<=25:  actions.append("⚠️ BESS ใกล้หมด")
    if diesel>0: actions.append("🔴 Diesel ทำงาน")
    soc_icon = "🔴" if soc<=25 else "🟡" if soc<=40 else "🟢"
    return mix, " | ".join(actions) or "ระบบปกติ", f"{soc_icon} {soc:.0f}%"

rows = []
for _,r in sdf.iterrows():
    mix,action,soc_str = get_action(r)
    rows.append({"ชั่วโมง":f"{int(r['hour']):02d}:00",
                 "Load":f"{r['load_kw']:.0f} kW",
                 "Energy Mix":mix,"BESS SOC":soc_str,"คำแนะนำ":action})

op_df = pd.DataFrame(rows)
def highlight(row):
    if "🔴" in str(row["คำแนะนำ"]):
        return ["background-color: rgba(239,68,68,0.12)"]*len(row)
    elif "⚠️" in str(row["คำแนะนำ"]):
        return ["background-color: rgba(245,158,11,0.10)"]*len(row)
    return [""]*len(row)

st.dataframe(op_df.style.apply(highlight,axis=1),
             use_container_width=True, hide_index=True, height=550)
st.caption("🟢 SOC ปกติ | 🟡 SOC ต่ำ | 🔴 ต้องดำเนินการทันที")
