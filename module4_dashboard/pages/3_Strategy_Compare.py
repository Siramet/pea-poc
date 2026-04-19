import streamlit as st
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

st.set_page_config(page_title="Strategy Compare", layout="wide", page_icon="📊")

from shared.synthetic_data import generate_load, generate_pv, get_site_config
from module2_optimization.app import rule_dispatch, COSTS

CONFIG = get_site_config()

with st.sidebar:
    st.title("📊 Strategy Compare")
    st.divider()
    selected_date = st.date_input("วันที่", value=pd.Timestamp("2024-06-15"))
    bess_soc = st.slider("BESS SOC เริ่มต้น (%)", 20, 90, 60)
    st.divider()
    use_bess_deg = st.toggle("รวมต้นทุน BESS", value=True)
    bess_deg_thb = st.slider("฿/cycle", 500, 2000, 1000, 100, disabled=not use_bess_deg)
    use_rec      = st.toggle("รวมรายได้ REC", value=True)
    rec_price    = st.slider("฿/MWh", 500, 3000, 1500, 100, disabled=not use_rec)
    use_carbon   = st.toggle("รวม Carbon Credit", value=True)
    carbon_usd   = st.slider("$/tCO₂", 1, 20, 5, 1, disabled=not use_carbon)
    usd_thb      = st.number_input("฿/$", 30.0, 40.0, 35.0, 0.5)
    baseline_cost_day = st.number_input("ค่าไฟ baseline/วัน (฿)", 5000, 50000, 18000, 500)

st.title("📊 Strategy Compare — เปรียบเทียบ 3 กลยุทธ์")
st.caption(f"วันที่ {selected_date}")

load_df = generate_load(str(selected_date), 24)
pv_df   = generate_pv(str(selected_date), 24)
forecast_raw = [{"datetime": str(load_df["ds"].iloc[i]),
                 "load_kw":  round(float(load_df["y"].iloc[i]), 1),
                 "pv_kw":    round(float(pv_df["y"].iloc[i]), 1),
                 "net_kw":   round(float(load_df["y"].iloc[i] - pv_df["y"].iloc[i]), 1)}
                for i in range(24)]

compare_rows = []
for strat in ["cost_minimize", "bess_protect", "green_first"]:
    s   = rule_dispatch(forecast_raw, bess_soc, strat)
    sdf = pd.DataFrame(s)
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
    label      = {"cost_minimize": "A — Cost Minimize",
                  "bess_protect":  "B — BESS Protect",
                  "green_first":   "C — Green First"}[strat]
    compare_rows.append({
        "กลยุทธ์":        label,
        "ค่าไฟ (฿)":      round(cost),
        "ประหยัด (฿)":    round(saving),
        "REC (฿)":        round(rec),
        "Carbon (฿)":     round(carbon_rev),
        "BESS cost (฿)":  round(bess_deg),
        "กำไรสุทธิ (฿)":  round(net),
        "PV (kWh)":       round(pv_kwh),
        "BESS (kWh)":     round(bess_kwh),
        "Grid (kWh)":     round(grid_kwh),
        "Diesel (kWh)":   round(diesel_kwh),
        "Diesel (L)":     round(diesel_L, 1),
        "CO₂ (tCO₂)":    round(co2, 3),
    })

cdf = pd.DataFrame(compare_rows).set_index("กลยุทธ์")

# กำไรสุทธิ
st.subheader("กำไรสุทธิ/วัน (฿)")
st.bar_chart(cdf[["กำไรสุทธิ (฿)"]], color=["#10B981"])

col1, col2 = st.columns(2)
with col1:
    st.subheader("ค่าไฟ/วัน (฿)")
    st.bar_chart(cdf[["ค่าไฟ (฿)"]], color=["#3B82F6"])
with col2:
    st.subheader("Source Mix (kWh)")
    st.bar_chart(cdf[["PV (kWh)","BESS (kWh)","Grid (kWh)","Diesel (kWh)"]],
                 color=["#F59E0B","#10B981","#3B82F6","#EF4444"])

# Diesel comparison
st.subheader("Diesel ที่ประหยัดได้เทียบ baseline")
baseline_diesel_L = baseline_cost_day / (COSTS["diesel_thb_liter"] * COSTS["diesel_liter_per_kwh"]) * COSTS["diesel_liter_per_kwh"]
diesel_df = cdf[["Diesel (L)"]].copy()
diesel_df["ประหยัดได้ (L)"] = (baseline_diesel_L - diesel_df["Diesel (L)"]).round(1)
diesel_df["ประหยัดได้ (฿)"] = (diesel_df["ประหยัดได้ (L)"] * COSTS["diesel_thb_liter"]).round(0)
diesel_df["CO₂ ลดได้ (kg)"] = (diesel_df["ประหยัดได้ (L)"] * 2.65).round(1)
st.bar_chart(diesel_df[["Diesel (L)","ประหยัดได้ (L)"]], color=["#EF4444","#10B981"])
st.dataframe(diesel_df, use_container_width=True)

st.divider()
st.subheader("ตารางสรุปทั้งหมด")
st.dataframe(cdf, use_container_width=True)
