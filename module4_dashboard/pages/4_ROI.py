import streamlit as st
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

st.set_page_config(page_title="ROI & Viability", layout="wide", page_icon="💰")

from shared.synthetic_data import generate_load, generate_pv, get_site_config
from module2_optimization.app import rule_dispatch, COSTS

CONFIG = get_site_config()

with st.sidebar:
    st.title("💰 ROI & Viability")
    st.divider()
    strategy = st.selectbox("กลยุทธ์",
        ["cost_minimize","bess_protect","green_first"],
        format_func=lambda x: {"cost_minimize":"A — Cost Minimize",
                                "bess_protect": "B — BESS Protect",
                                "green_first":  "C — Green First"}[x])
    bess_soc = st.slider("BESS SOC (%)", 20, 90, 60)
    st.divider()
    baseline_cost_day = st.number_input("ค่าไฟ baseline/วัน (฿)", 5000, 50000, 18000, 500)
    system_cost_mthb  = st.number_input("ต้นทุนระบบ (ล้านบาท)", 1.0, 50.0, 15.0, 0.5)

st.title("💰 ROI & Viability")
st.caption("ผลตอบแทนทางการเงินและความคุ้มค่าของระบบ")

# ROI Toggles
st.subheader("ปรับตัวแปร")
r1, r2, r3 = st.columns(3)
with r1:
    st.markdown("**ต้นทุน BESS**")
    use_bess_deg = st.toggle("รวมต้นทุน BESS", value=True)
    bess_deg_thb = st.slider("฿/cycle", 500, 2000, 1000, 100, disabled=not use_bess_deg)
with r2:
    st.markdown("**REC Revenue**")
    use_rec   = st.toggle("รวมรายได้ REC", value=True)
    rec_price = st.slider("฿/MWh", 500, 3000, 1500, 100, disabled=not use_rec)
with r3:
    st.markdown("**Carbon Credit**")
    use_carbon   = st.toggle("รวม Carbon Credit", value=True)
    carbon_usd   = st.slider("$/tCO₂", 1, 20, 5, 1, disabled=not use_carbon)
    usd_thb      = st.number_input("฿/$", 30.0, 40.0, 35.0, 0.5)

st.divider()

# คำนวณ
load_df = generate_load("2024-06-15", 24)
pv_df   = generate_pv("2024-06-15", 24)
forecast_raw = [{"datetime": str(load_df["ds"].iloc[i]),
                 "load_kw":  round(float(load_df["y"].iloc[i]), 1),
                 "pv_kw":    round(float(pv_df["y"].iloc[i]), 1),
                 "net_kw":   round(float(load_df["y"].iloc[i] - pv_df["y"].iloc[i]), 1)}
                for i in range(24)]
schedule = rule_dispatch(forecast_raw, bess_soc, strategy)
sdf = pd.DataFrame(schedule)

cost_day    = sdf["cost_thb"].sum()
pv_mwh_day  = sdf["pv_kw"].clip(lower=0).sum() / 1000
diesel_L    = sdf["diesel_kw"].sum() * COSTS["diesel_liter_per_kwh"]
co2_day     = (pv_mwh_day * 0.45) + (diesel_L * 2.65 / 1000)
bess_kwh    = sdf["bess_kw"].clip(lower=0).sum()
bess_cyc    = bess_kwh / CONFIG["bess_capacity_kwh"]
bess_deg    = (bess_cyc * bess_deg_thb) if use_bess_deg else 0
rec_day     = (pv_mwh_day * rec_price) if use_rec else 0
carbon_day  = (co2_day * carbon_usd * usd_thb) if use_carbon else 0
saving_day  = baseline_cost_day - cost_day
net_day     = saving_day + rec_day + carbon_day - bess_deg
net_year    = net_day * 365
system_cost = system_cost_mthb * 1_000_000
payback     = system_cost / net_year if net_year > 0 else 999
roi_5yr     = (net_year * 5 - system_cost) / system_cost * 100

# แสดงผล ROI
st.subheader("ผลตอบแทน/ปี")
m1, m2, m3, m4 = st.columns(4)
m1.metric("ประหยัดค่าไฟ/ปี",  f"฿{saving_day*365:,.0f}", f"฿{saving_day:,.0f}/วัน")
m2.metric("REC + Carbon/ปี",  f"฿{(rec_day+carbon_day)*365:,.0f}", f"฿{rec_day+carbon_day:,.0f}/วัน")
m3.metric("ต้นทุน BESS/ปี",   f"฿{bess_deg*365:,.0f}", f"{bess_cyc:.3f} cycles/วัน", delta_color="off")
m4.metric("กำไรสุทธิ/ปี",     f"฿{net_year:,.0f}", f"฿{net_day:,.0f}/วัน",
          delta_color="normal" if net_day > 0 else "inverse")

st.divider()

p1, p2 = st.columns(2)
p1.metric("Payback Period", f"{payback:.1f} ปี",
          delta="คุ้มค่า" if payback < 7 else "ควรทบทวน",
          delta_color="normal" if payback < 7 else "inverse")
p2.metric("ROI 5 ปี", f"{roi_5yr:.0f}%",
          delta="คุ้มค่า" if roi_5yr > 0 else "ยังไม่คุ้ม",
          delta_color="normal" if roi_5yr > 0 else "inverse")

st.divider()

# Implementation Timeline
st.subheader("Implementation Timeline")
st.caption("แผนการสร้างระบบจริงพร้อมติดตั้งใช้งาน")

timeline = [
    {"เดือน": "1-2",  "Phase": "Data Integration",
     "งาน": "ติดตั้ง SCADA connector + real-time data pipeline จาก Smart Meter",
     "Deliverable": "ข้อมูล Load/PV รายชั่วโมงแบบ real-time"},
    {"เดือน": "3-4",  "Phase": "Model Training",
     "งาน": "Train Prophet + XGBoost ด้วยข้อมูลจริง + validate MAPE ≤ 10%",
     "Deliverable": "Forecast model ที่ผ่าน MAPE threshold"},
    {"เดือน": "5-6",  "Phase": "Optimization Deploy",
     "งาน": "Deploy LP optimizer + Early Warning บน production server",
     "Deliverable": "API endpoints พร้อมใช้งาน"},
    {"เดือน": "7-8",  "Phase": "Dashboard + UAT",
     "งาน": "Operator dashboard + ทดสอบกับทีม PEA + แก้ไขตาม feedback",
     "Deliverable": "Dashboard ผ่าน UAT"},
    {"เดือน": "9-10", "Phase": "Pilot Run",
     "งาน": "รัน parallel กับระบบเดิม 2 เดือน เปรียบเทียบผล",
     "Deliverable": "รายงานผล pilot + ROI จริง"},
    {"เดือน": "11-12","Phase": "Go-Live",
     "งาน": "เปิดใช้งานจริง + training operator + handover document",
     "Deliverable": "ระบบ production พร้อมใช้งาน"},
]

tl_df = pd.DataFrame(timeline)
st.dataframe(tl_df.set_index("เดือน"), use_container_width=True, hide_index=False)

st.success("ระบบพร้อม Go-Live ภายใน **12 เดือน** — ROI คืนทุนภายใน "
           f"**{payback:.1f} ปี** จากเงินลงทุน ฿{system_cost_mthb:.0f} ล้านบาท")

st.caption("* คำนวณจาก synthetic data — จะแม่นยำขึ้นเมื่อใช้ข้อมูลจริงจาก PEA")
