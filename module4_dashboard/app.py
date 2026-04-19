import streamlit as st
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

st.set_page_config(page_title="PEA Energy Dashboard", layout="wide", page_icon="⚡")

from shared.synthetic_data import generate_load, generate_pv, get_site_config
from module2_optimization.app import rule_dispatch

CONFIG = get_site_config()
COSTS  = CONFIG["costs"]

@st.cache_data
def get_forecast(start_date):
    load_df = generate_load(str(start_date), 24)
    pv_df   = generate_pv(str(start_date), 24)
    rows = []
    for i in range(24):
        rows.append({"datetime": load_df["ds"].iloc[i],
                     "hour": load_df["ds"].iloc[i].hour,
                     "load_kw": round(float(load_df["y"].iloc[i]), 1),
                     "pv_kw":   round(float(pv_df["y"].iloc[i]), 1)})
    df = pd.DataFrame(rows)
    df["net_kw"] = (df["load_kw"] - df["pv_kw"]).round(1)
    return df

# ── Sidebar ────────────────────────────────────────────────────────────────
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
    st.divider()
    baseline_cost_day = st.number_input("ค่าไฟ baseline/วัน (฿)", 5000, 50000, 18000, 500)
    system_cost_mthb  = st.number_input("ต้นทุนระบบ (ล้านบาท)", 1.0, 50.0, 15.0, 0.5)

# ── Data ───────────────────────────────────────────────────────────────────
forecast_df  = get_forecast(selected_date)
forecast_raw = [{"datetime":str(r["datetime"]),"load_kw":r["load_kw"],
                 "pv_kw":r["pv_kw"],"net_kw":r["net_kw"]}
                for _, r in forecast_df.iterrows()]
schedule_raw = rule_dispatch(forecast_raw, bess_soc, strategy)
schedule_df  = pd.DataFrame(schedule_raw)
if "hour" not in schedule_df.columns:
    schedule_df["hour"] = pd.to_datetime(schedule_df["datetime"]).dt.hour

# ── Header ─────────────────────────────────────────────────────────────────
st.title("PEA Energy Resource Dashboard")
st.caption(f"วันที่ {selected_date} | กลยุทธ์: {strategy.replace('_',' ').title()}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Peak Load",  f"{schedule_df['load_kw'].max():.0f} kW")
c2.metric("PV รวม",     f"{schedule_df['pv_kw'].sum():.0f} kWh")
c3.metric("ค่าไฟรวม",   f"฿{schedule_df['cost_thb'].sum():,.0f}")
c4.metric("Diesel",     f"{schedule_df['diesel_kw'].sum()*COSTS['diesel_liter_per_kwh']:.0f} L")

st.divider()

# ── Dispatch Chart ─────────────────────────────────────────────────────────
st.subheader("Dispatch Schedule 24 ชั่วโมง")
chart_df = schedule_df[["pv_kw","bess_kw","grid_kw","diesel_kw"]]
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
        if level == "critical": st.error(f"⛔ {msg}")
        else: st.warning(f"⚠️ {msg}")

st.divider()

# ── ROI Calculator ─────────────────────────────────────────────────────────
st.subheader("ROI Calculator")
st.caption("ปรับ toggle และ slider เพื่อดูผลตอบแทนแบบ real-time")

roi1, roi2, roi3 = st.columns(3)

with roi1:
    st.markdown("**ต้นทุน BESS Degradation**")
    use_bess_deg  = st.toggle("รวมต้นทุน BESS", value=True, key="bess_deg")
    bess_deg_thb  = st.slider("฿/cycle", 500, 2000, 1000, 100,
                               disabled=not use_bess_deg, key="bess_deg_price")

with roi2:
    st.markdown("**REC Revenue**")
    use_rec       = st.toggle("รวมรายได้ REC", value=True, key="rec")
    rec_price     = st.slider("฿/MWh", 500, 3000, 1500, 100,
                               disabled=not use_rec, key="rec_price")

with roi3:
    st.markdown("**Carbon Credit**")
    use_carbon    = st.toggle("รวม Carbon Credit", value=True, key="carbon")
    carbon_usd    = st.slider("$/tCO₂", 1, 20, 5, 1,
                               disabled=not use_carbon, key="carbon_price")
    usd_thb       = st.number_input("฿/$", 30.0, 40.0, 35.0, 0.5, key="fx")

st.divider()

# ── คำนวณ ROI ──────────────────────────────────────────────────────────────
cost_day      = schedule_df["cost_thb"].sum()
pv_mwh_day    = total_pv / 1000
diesel_L_day  = total_diesel * COSTS["diesel_liter_per_kwh"]
co2_saved_day = (pv_mwh_day * 0.45) + (diesel_L_day * 2.65 / 1000)

# BESS cycles/วัน
bess_kwh_day  = schedule_df["bess_kw"].clip(lower=0).sum()
bess_cycles   = bess_kwh_day / CONFIG["bess_capacity_kwh"]
bess_deg_day  = (bess_cycles * bess_deg_thb) if use_bess_deg else 0

# รายได้/วัน
rec_day       = (pv_mwh_day * rec_price) if use_rec else 0
carbon_day    = (co2_saved_day * carbon_usd * usd_thb) if use_carbon else 0

# กำไรสุทธิ/วัน
saving_day    = baseline_cost_day - cost_day
net_day       = saving_day + rec_day + carbon_day - bess_deg_day
net_year      = net_day * 365

system_cost   = system_cost_mthb * 1_000_000
payback       = system_cost / net_year if net_year > 0 else 999
roi_5yr       = (net_year * 5 - system_cost) / system_cost * 100

# แสดงผล
r1, r2, r3, r4 = st.columns(4)
r1.metric("ประหยัดค่าไฟ/ปี",   f"฿{saving_day*365:,.0f}",
          delta=f"฿{saving_day:,.0f}/วัน")
r2.metric("REC + Carbon/ปี",
          f"฿{(rec_day+carbon_day)*365:,.0f}",
          delta=f"฿{rec_day+carbon_day:,.0f}/วัน")
r3.metric("ต้นทุน BESS/ปี",
          f"฿{bess_deg_day*365:,.0f}",
          delta=f"{bess_cycles:.3f} cycles/วัน",
          delta_color="off")
r4.metric("กำไรสุทธิ/ปี",      f"฿{net_year:,.0f}",
          delta=f"฿{net_day:,.0f}/วัน",
          delta_color="normal" if net_day > 0 else "inverse")

st.divider()

p1, p2 = st.columns(2)
p1.metric("Payback Period",
          f"{payback:.1f} ปี",
          delta="คุ้มค่า" if payback < 7 else "ควรทบทวน",
          delta_color="normal" if payback < 7 else "inverse")
p2.metric("ROI 5 ปี",
          f"{roi_5yr:.0f}%",
          delta="คุ้มค่า" if roi_5yr > 0 else "ยังไม่คุ้ม",
          delta_color="normal" if roi_5yr > 0 else "inverse")

st.divider()


st.divider()

# ── Strategy Compare ───────────────────────────────────────────────────────
st.subheader("เปรียบเทียบ 3 กลยุทธ์")

compare_rows = []
for strat in ["cost_minimize", "bess_protect", "green_first"]:
    s = rule_dispatch(forecast_raw, bess_soc, strat)
    sdf = pd.DataFrame(s)
    if "hour" not in sdf.columns:
        sdf["hour"] = pd.to_datetime(sdf["datetime"]).dt.hour
    pv_kwh     = sdf["pv_kw"].clip(lower=0).sum()
    bess_kwh   = sdf["bess_kw"].clip(lower=0).sum()
    grid_kwh   = sdf["grid_kw"].sum()
    diesel_kwh = sdf["diesel_kw"].sum()
    cost       = sdf["cost_thb"].sum()
    diesel_L   = diesel_kwh * COSTS["diesel_liter_per_kwh"]
    co2        = (pv_kwh/1000*0.45) + (diesel_L*2.65/1000)
    bess_cyc   = bess_kwh / CONFIG["bess_capacity_kwh"]
    bess_deg   = (bess_cyc * bess_deg_thb) if use_bess_deg else 0
    rec        = (pv_kwh/1000 * rec_price) if use_rec else 0
    carbon_rev = (co2 * carbon_usd * usd_thb) if use_carbon else 0
    saving     = baseline_cost_day - cost
    net        = saving + rec + carbon_rev - bess_deg
    label      = {"cost_minimize":"A — Cost Minimize",
                  "bess_protect": "B — BESS Protect",
                  "green_first":  "C — Green First"}[strat]
    compare_rows.append({
        "กลยุทธ์":      label,
        "ค่าไฟ (฿)":    round(cost, 0),
        "PV (kWh)":     round(pv_kwh, 0),
        "BESS (kWh)":   round(bess_kwh, 0),
        "Grid (kWh)":   round(grid_kwh, 0),
        "Diesel (kWh)": round(diesel_kwh, 0),
        "CO₂ (tCO₂)":  round(co2, 3),
        "REC (฿)":      round(rec, 0),
        "Carbon (฿)":   round(carbon_rev, 0),
        "BESS cost (฿)":round(bess_deg, 0),
        "กำไรสุทธิ (฿)":round(net, 0),
    })

cdf = pd.DataFrame(compare_rows).set_index("กลยุทธ์")

# Bar chart กำไรสุทธิ
st.markdown("**กำไรสุทธิ/วัน (฿) — รวม REC, Carbon, BESS cost ตาม toggle**")
profit_df = cdf[["กำไรสุทธิ (฿)"]].copy()
st.bar_chart(profit_df, color=["#10B981"])

# Bar chart ค่าไฟ
st.markdown("**ค่าไฟ/วัน (฿)**")
cost_df = cdf[["ค่าไฟ (฿)"]].copy()
st.bar_chart(cost_df, color=["#3B82F6"])

# Source mix comparison
st.markdown("**Source Mix เปรียบเทียบ (kWh)**")
mix_df = cdf[["PV (kWh)","BESS (kWh)","Grid (kWh)","Diesel (kWh)"]].copy()
st.bar_chart(mix_df, color=["#F59E0B","#10B981","#3B82F6","#EF4444"])

# Diesel comparison
st.markdown("**Diesel ที่ประหยัดได้เทียบ baseline (ลิตร/วัน)**")
baseline_diesel_L = baseline_cost_day / (COSTS["diesel_thb_liter"] * COSTS["diesel_liter_per_kwh"]) * COSTS["diesel_liter_per_kwh"]
diesel_compare = cdf[["Diesel (kWh)"]].copy()
diesel_compare["Diesel จริง (L)"] = (diesel_compare["Diesel (kWh)"] * COSTS["diesel_liter_per_kwh"]).round(1)
diesel_compare["ประหยัดได้ (L)"] = (baseline_diesel_L - diesel_compare["Diesel จริง (L)"]).round(1)
diesel_compare["ประหยัดได้ (฿)"] = (diesel_compare["ประหยัดได้ (L)"] * COSTS["diesel_thb_liter"]).round(0)
diesel_compare["CO₂ ลดได้ (kg)"] = (diesel_compare["ประหยัดได้ (L)"] * 2.65).round(1)
st.bar_chart(diesel_compare[["Diesel จริง (L)","ประหยัดได้ (L)"]], color=["#EF4444","#10B981"])
st.dataframe(diesel_compare.drop(columns=["Diesel (kWh)"]), use_container_width=True)

# ตาราง summary
st.markdown("**ตารางสรุปทั้งหมด**")
st.dataframe(cdf, use_container_width=True)


st.divider()

# ── Operator Recommendations ───────────────────────────────────────────────
st.subheader("คำแนะนำสำหรับ Operator — รายชั่วโมง")
st.caption("Energy mix และการดำเนินการที่แนะนำทุกชั่วโมง")

def get_recommendation(row):
    h     = int(row["hour"])
    load  = row["load_kw"]
    pv    = row["pv_kw"]
    bess  = row["bess_kw"]
    grid  = row["grid_kw"]
    soc   = row["bess_soc_pct"]
    diesel= row["diesel_kw"]
    total = load if load > 0 else 1

    # Priority label
    sources = []
    if pv > 0:    sources.append(f"PV {pv:.0f} kW ({pv/total*100:.0f}%)")
    if bess > 0:  sources.append(f"BESS {bess:.0f} kW ({bess/total*100:.0f}%)")
    if grid > 0:  sources.append(f"Grid {grid:.0f} kW ({grid/total*100:.0f}%)")
    if diesel > 0:sources.append(f"Diesel {diesel:.0f} kW ({diesel/total*100:.0f}%)")
    mix_str = " + ".join(sources) if sources else "Grid only"

    # คำแนะนำ
    actions = []
    if 0 <= h <= 5:
        actions.append("ช่วง Off-peak — Charge BESS จาก Grid ราคาถูก")
    if 6 <= h <= 8:
        actions.append("PV เริ่มขึ้น — ลด Grid import ทีละน้อย")
    if 9 <= h <= 16 and pv > load * 0.5:
        actions.append("PV แรง — ใช้ PV เป็นหลัก เก็บ BESS ไว้")
    if 17 <= h <= 20:
        actions.append("PV ลด — เริ่ม Discharge BESS ชดเชย")
    if 21 <= h <= 23:
        actions.append("กลางคืน — ใช้ Grid Off-peak ประหยัดต้นทุน")
    if load >= CONFIG["load_peak_kw"] * 0.80:
        actions.append("⚠️ Load สูง — Discharge BESS เต็มกำลัง")
    if soc <= 25:
        actions.append("⚠️ BESS ใกล้หมด — เตรียม Grid/Diesel สำรอง")
    if soc >= 85:
        actions.append("BESS เต็ม — หยุด Charge รับ PV โดยตรง")
    if diesel > 0:
        actions.append("🔴 Diesel ทำงาน — ตรวจสอบ Grid และ BESS")

    action_str = " | ".join(actions) if actions else "ระบบปกติ — ไม่มีการแนะนำพิเศษ"
    return mix_str, action_str

# สร้าง recommendation table
rec_rows = []
for _, row in schedule_df.iterrows():
    mix_str, action_str = get_recommendation(row)
    soc = row["bess_soc_pct"]
    # SOC status
    if soc <= 25:   soc_status = f"🔴 {soc:.0f}%"
    elif soc <= 40: soc_status = f"🟡 {soc:.0f}%"
    else:           soc_status = f"🟢 {soc:.0f}%"

    rec_rows.append({
        "ชั่วโมง":        f"{int(row['hour']):02d}:00",
        "Load (kW)":     f"{row['load_kw']:.0f}",
        "Energy Mix":    mix_str,
        "BESS SOC":      soc_status,
        "คำแนะนำ Operator": action_str,
    })

rec_df = pd.DataFrame(rec_rows)

# Highlight rows ที่มี alert
def highlight_row(row):
    if "🔴" in str(row["คำแนะนำ Operator"]) or "⚠️" in str(row["คำแนะนำ Operator"]):
        return ["background-color: rgba(239,68,68,0.15)"] * len(row)
    elif "🟡" in str(row["BESS SOC"]):
        return ["background-color: rgba(245,158,11,0.10)"] * len(row)
    else:
        return [""] * len(row)

st.dataframe(
    rec_df.style.apply(highlight_row, axis=1),
    use_container_width=True,
    hide_index=True,
    height=600,
)

st.caption("🟢 BESS SOC ปกติ | 🟡 SOC ต่ำ ควรระวัง | 🔴 ต้องดำเนินการทันที")

with st.expander("ดู Dispatch Schedule ทั้งหมด"):
    st.dataframe(schedule_df.set_index("hour"), use_container_width=True)

st.caption("* คำนวณจาก synthetic data — จะแม่นยำขึ้นเมื่อใช้ข้อมูลจริงจาก PEA")
