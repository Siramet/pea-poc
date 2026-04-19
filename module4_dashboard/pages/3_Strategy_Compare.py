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
    carbon_usd   = st.slider("$/tCO2", 1, 20, 5, 1, disabled=not use_carbon)
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

strategies = {
    "cost_minimize": "A — Cost Minimize",
    "bess_protect":  "B — BESS Protect",
    "green_first":   "C — Green First",
}

results = {}
for strat, label in strategies.items():
    s   = rule_dispatch(forecast_raw, bess_soc, strat)
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
    results[strat] = {
        "label": label, "sdf": sdf,
        "cost": cost, "saving": saving, "net": net,
        "pv_kwh": pv_kwh, "bess_kwh": bess_kwh,
        "grid_kwh": grid_kwh, "diesel_kwh": diesel_kwh,
        "diesel_L": diesel_L, "co2": co2,
        "rec": rec, "carbon_rev": carbon_rev, "bess_deg": bess_deg,
    }

# หา best strategy
best_strat = max(results, key=lambda k: results[k]["net"])

# ── Section 1: Summary Cards ───────────────────────────────────────────────
st.subheader("สรุปเปรียบเทียบ")
cols = st.columns(3)
for idx, (strat, label) in enumerate(strategies.items()):
    r = results[strat]
    is_best = strat == best_strat
    with cols[idx]:
        if is_best:
            st.success(f"⭐ **{label}** — แนะนำ")
        else:
            st.info(f"**{label}**")
        st.metric("ค่าไฟ/วัน",      f"฿{r['cost']:,.0f}")
        st.metric("ประหยัด/วัน",     f"฿{r['saving']:,.0f}")
        st.metric("กำไรสุทธิ/วัน",   f"฿{r['net']:,.0f}",
                  delta="★ Best" if is_best else "",
                  delta_color="normal" if is_best else "off")
        st.metric("Diesel",          f"{r['diesel_L']:.0f} L")
        st.metric("CO₂ ลดได้",       f"{r['co2']:.2f} tCO₂")

st.divider()

# ── Section 2: Dispatch 24h แต่ละกลยุทธ์ ──────────────────────────────────
st.subheader("Dispatch Schedule 24h — แต่ละกลยุทธ์")
d1, d2, d3 = st.columns(3)
dispatch_cols = [d1, d2, d3]
for idx, (strat, label) in enumerate(strategies.items()):
    sdf = results[strat]["sdf"]
    with dispatch_cols[idx]:
        st.caption(label)
        chart = sdf[["hour","pv_kw","bess_kw","grid_kw","diesel_kw"]].set_index("hour")
        chart.columns = ["PV","BESS","Grid","Diesel"]
        st.bar_chart(chart, color=["#F59E0B","#10B981","#3B82F6","#EF4444"])

st.divider()

# ── Section 3: Financial Compare ──────────────────────────────────────────
st.subheader("เปรียบเทียบผลตอบแทน")
fc1, fc2 = st.columns(2)
with fc1:
    st.caption("กำไรสุทธิ/วัน (฿)")
    net_df = pd.DataFrame({
        "กำไรสุทธิ": [results[s]["net"] for s in strategies]
    }, index=[results[s]["label"] for s in strategies])
    st.bar_chart(net_df, color=["#10B981"])
with fc2:
    st.caption("ค่าไฟ/วัน (฿)")
    cost_df = pd.DataFrame({
        "ค่าไฟ": [results[s]["cost"] for s in strategies]
    }, index=[results[s]["label"] for s in strategies])
    st.bar_chart(cost_df, color=["#3B82F6"])

st.divider()

# ── Section 4: Source Mix ──────────────────────────────────────────────────
st.subheader("Source Mix เปรียบเทียบ")
sm1, sm2 = st.columns(2)
with sm1:
    st.caption("Source Mix (kWh)")
    mix_df = pd.DataFrame({
        "PV":     [results[s]["pv_kwh"]      for s in strategies],
        "BESS":   [results[s]["bess_kwh"]    for s in strategies],
        "Grid":   [results[s]["grid_kwh"]    for s in strategies],
        "Diesel": [results[s]["diesel_kwh"]  for s in strategies],
    }, index=[results[s]["label"] for s in strategies])
    st.bar_chart(mix_df, color=["#F59E0B","#10B981","#3B82F6","#EF4444"])
with sm2:
    st.caption("Diesel ที่ประหยัดได้ (L)")
    baseline_L = baseline_cost_day / (COSTS["diesel_thb_liter"] * COSTS["diesel_liter_per_kwh"]) * COSTS["diesel_liter_per_kwh"]
    diesel_df = pd.DataFrame({
        "Diesel จริง (L)":   [results[s]["diesel_L"] for s in strategies],
        "ประหยัดได้ (L)": [max(0, baseline_L - results[s]["diesel_L"]) for s in strategies],
    }, index=[results[s]["label"] for s in strategies])
    st.bar_chart(diesel_df, color=["#EF4444","#10B981"])

st.divider()

# ── Section 5: Summary Table ───────────────────────────────────────────────
st.subheader("ตารางสรุปทั้งหมด")
table_rows = []
for strat, label in strategies.items():
    r = results[strat]
    table_rows.append({
        "กลยุทธ์":        label + (" ⭐" if strat==best_strat else ""),
        "ค่าไฟ (฿)":      round(r["cost"]),
        "ประหยัด (฿)":    round(r["saving"]),
        "REC (฿)":        round(r["rec"]),
        "Carbon (฿)":     round(r["carbon_rev"]),
        "BESS cost (฿)":  round(r["bess_deg"]),
        "กำไรสุทธิ (฿)":  round(r["net"]),
        "Diesel (L)":     round(r["diesel_L"], 1),
        "CO₂ (tCO₂)":    round(r["co2"], 3),
    })
st.dataframe(pd.DataFrame(table_rows).set_index("กลยุทธ์"),
             use_container_width=True)
st.caption(f"⭐ = กลยุทธ์แนะนำตามเงื่อนไขปัจจุบัน (กำไรสุทธิสูงสุด)")
