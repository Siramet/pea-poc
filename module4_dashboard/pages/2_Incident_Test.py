import streamlit as st
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

st.set_page_config(page_title="Incident Test", layout="wide", page_icon="⚡")

from shared.synthetic_data import generate_load, generate_pv, get_site_config
from module2_optimization.app import rule_dispatch, COSTS
from module3_early_warning.app import check_alerts

CONFIG = get_site_config()

with st.sidebar:
    st.title("⚡ Incident Test")
    st.divider()
    strategy = st.selectbox("กลยุทธ์",
        ["cost_minimize","bess_protect","green_first"],
        format_func=lambda x: {"cost_minimize":"A — Cost Minimize",
                                "bess_protect": "B — BESS Protect",
                                "green_first":  "C — Green First"}[x])
    bess_soc = st.slider("BESS SOC เริ่มต้น (%)", 20, 90, 60)

st.title("⚡ Incident Test — Live Model Evaluation")
st.caption("กรรมการกำหนด incident → ระบบตรวจจับล่วงหน้าและแนะนำการตอบสนอง")

# ── Step 1 ─────────────────────────────────────────────────────────────────
st.subheader("Step 1 — ข้อมูล")
data_mode = st.radio("แหล่งข้อมูล",
    ["Synthetic Data (ทดสอบทันที)", "Upload CSV จากกรรมการ"], horizontal=True)

if data_mode == "Upload CSV จากกรรมการ":
    st.info("CSV ต้องมี columns: datetime, load_kw, pv_kw (รายชั่วโมง)")
    uploaded = st.file_uploader("Upload dataset", type=["csv"])
    if uploaded:
        df_raw = pd.read_csv(uploaded, parse_dates=["datetime"])
        df_raw = df_raw.sort_values("datetime").reset_index(drop=True)
        st.success(f"โหลดสำเร็จ — {len(df_raw)} rows ({df_raw['datetime'].min().date()} ถึง {df_raw['datetime'].max().date()})")
    else:
        st.warning("กรุณา upload CSV")
        st.stop()
else:
    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("วันเริ่มต้น", value=pd.Timestamp("2026-01-01"))
    with c2:
        n_days = st.slider("จำนวนวัน context", 3, 14, 9)
    load_rows, pv_rows = [], []
    for d in range(n_days):
        date = pd.Timestamp(start_date) + pd.Timedelta(days=d)
        load_rows.append(generate_load(str(date.date()), 24))
        pv_rows.append(generate_pv(str(date.date()), 24))
    df_load = pd.concat(load_rows).reset_index(drop=True)
    df_pv   = pd.concat(pv_rows).reset_index(drop=True)
    df_raw  = pd.DataFrame({"datetime": df_load["ds"],
                             "load_kw": df_load["y"], "pv_kw": df_pv["y"]})
    st.success(f"Synthetic data {n_days} วัน — {df_raw['datetime'].min().date()} ถึง {df_raw['datetime'].max().date()}")

st.divider()

# ── Step 2 ─────────────────────────────────────────────────────────────────
st.subheader("Step 2 — กำหนด Incident (กรรมการป้อน)")

col1, col2 = st.columns(2)
with col1:
    incident_type = st.selectbox("ประเภท Incident", [
        "Grid Trip — ไฟจาก Grid หายกะทันหัน",
        "PV Drop — PV ลดกะทันหัน (เมฆ/ฝน)",
        "Load Spike — Load พุ่งสูงกะทันหัน",
    ])
    incident_date = st.date_input("วันที่เกิด Incident",
        value=pd.Timestamp(df_raw["datetime"].max().date()))
    incident_hour = st.slider("ชั่วโมงที่เกิด", 0, 23, 14)
with col2:
    severity  = st.slider("Severity (%)", 10, 100, 70)
    duration  = st.slider("Duration (ชั่วโมง)", 1, 12, 3)
    warn_hours= st.slider("Early Warning ล่วงหน้า (ชั่วโมง)", 1, 24, 2)

inc_start  = pd.Timestamp(incident_date).replace(hour=incident_hour)
inc_end    = inc_start + pd.Timedelta(hours=duration)
warn_start = inc_start - pd.Timedelta(hours=warn_hours)

pc1, pc2, pc3 = st.columns(3)
pc1.info(f"⚠️ Early Warning\n\n**{warn_start.strftime('%d %b %H:%M')}**")
pc2.error(f"⛔ Incident เริ่ม\n\n**{inc_start.strftime('%d %b %H:%M')}**")
pc3.success(f"✅ คาดว่า recover\n\n**{inc_end.strftime('%d %b %H:%M')}**")

run_btn = st.button("▶ Run Incident Simulation", type="primary", use_container_width=True)
if not run_btn:
    st.stop()

st.divider()

# ── Step 3: Simulate ───────────────────────────────────────────────────────
with st.spinner("กำลังรัน simulation..."):
    inc_load = generate_load(str(incident_date), 24)
    inc_pv   = generate_pv(str(incident_date), 24)
    forecast_normal, forecast_incident = [], []
    for i in range(24):
        ts  = inc_load["ds"].iloc[i]
        lkw = round(float(inc_load["y"].iloc[i]), 1)
        pkw = round(float(inc_pv["y"].iloc[i]), 1)
        h   = ts.hour
        lkw_inc, pkw_inc, grid_cap = lkw, pkw, 1.0
        if inc_start.hour <= h < inc_end.hour:
            itype = incident_type.split("—")[0].strip()
            if "Grid Trip" in itype:   grid_cap = 1 - severity/100
            elif "PV Drop" in itype:   pkw_inc  = round(pkw*(1-severity/100), 1)
            elif "Load Spike" in itype: lkw_inc = round(lkw*(1+severity/100), 1)
        forecast_normal.append({"datetime":str(ts),"load_kw":lkw,"pv_kw":pkw,"net_kw":round(lkw-pkw,1),"hour":h,"grid_cap_pct":1.0})
        forecast_incident.append({"datetime":str(ts),"load_kw":lkw_inc,"pv_kw":pkw_inc,"net_kw":round(lkw_inc-pkw_inc,1),"hour":h,"grid_cap_pct":grid_cap})

    sch_n = rule_dispatch(forecast_normal,   bess_soc, strategy)
    sch_i = rule_dispatch(forecast_incident, bess_soc, strategy)
    sdf_n = pd.DataFrame(sch_n)
    sdf_i = pd.DataFrame(sch_i)
    if "hour" not in sdf_n.columns:
        sdf_n["hour"] = pd.to_datetime(sdf_n["datetime"]).dt.hour
        sdf_i["hour"] = pd.to_datetime(sdf_i["datetime"]).dt.hour

# ── Summary ────────────────────────────────────────────────────────────────
st.subheader("Step 3 — ผลการ Simulation")
n_warn = warn_hours
st.success(f"✅ ระบบตรวจจับ Early Warning **{n_warn} ชั่วโมง** ล่วงหน้า ({warn_start.strftime('%H:%M')} → {inc_start.strftime('%H:%M')})")

cost_n = sdf_n["cost_thb"].sum()
cost_i = sdf_i["cost_thb"].sum()
diesel_n = sdf_n["diesel_kw"].sum() * COSTS["diesel_liter_per_kwh"]
diesel_i = sdf_i["diesel_kw"].sum() * COSTS["diesel_liter_per_kwh"]

s1,s2,s3,s4 = st.columns(4)
s1.metric("ค่าไฟปกติ",      f"฿{cost_n:,.0f}")
s2.metric("ค่าไฟ Incident",  f"฿{cost_i:,.0f}",
          delta=f"฿{cost_i-cost_n:,.0f}", delta_color="inverse")
s3.metric("Diesel ปกติ",     f"{diesel_n:.0f} L")
s4.metric("Diesel Incident",  f"{diesel_i:.0f} L",
          delta=f"{diesel_i-diesel_n:+.0f} L", delta_color="inverse")

st.divider()

# ── Dispatch Comparison ────────────────────────────────────────────────────
st.subheader("Dispatch — ปกติ vs Incident")
dc1, dc2 = st.columns(2)
with dc1:
    st.caption("ปกติ (ไม่มี incident)")
    nc = sdf_n[["hour","pv_kw","bess_kw","grid_kw","diesel_kw"]].set_index("hour")
    nc.columns = ["PV","BESS","Grid","Diesel"]
    st.bar_chart(nc, color=["#F59E0B","#10B981","#3B82F6","#EF4444"])
with dc2:
    st.caption(f"Incident: {incident_type.split('—')[0].strip()} {severity}%")
    ic = sdf_i[["hour","pv_kw","bess_kw","grid_kw","diesel_kw"]].set_index("hour")
    ic.columns = ["PV","BESS","Grid","Diesel"]
    st.bar_chart(ic, color=["#F59E0B","#10B981","#3B82F6","#EF4444"])

st.divider()

# ── BESS SOC ───────────────────────────────────────────────────────────────
st.subheader("BESS SOC — ผลกระทบจาก Incident")
soc_df = pd.DataFrame({
    "ปกติ (%)":    sdf_n["bess_soc_pct"].values,
    "Incident (%)": sdf_i["bess_soc_pct"].values,
}, index=sdf_n["hour"].values)
st.line_chart(soc_df, color=["#10B981","#EF4444"])

st.divider()

# ── Early Warning Timeline (simplified) ───────────────────────────────────
st.subheader("Early Warning Timeline")
timeline_rows = []
for h in range(24):
    ts  = pd.Timestamp(incident_date).replace(hour=h)
    si  = forecast_incident[h]
    soc = sdf_i["bess_soc_pct"].iloc[h]
    soc_icon = "🔴" if soc<=25 else "🟡" if soc<=40 else "🟢"

    if ts == inc_start:
        status = "⛔ INCIDENT"
        msg    = f"{incident_type.split('—')[1].strip()} (severity {severity}%)"
        rec    = "ดำเนินการฉุกเฉินทันที"
    elif inc_start.hour <= h < inc_end.hour:
        status = "⛔ INCIDENT"
        msg    = f"Incident กำลังเกิด ชม.ที่ {h-inc_start.hour+1}/{duration}"
        rec    = "รักษา dispatch ตาม emergency plan"
    elif warn_start.hour <= h < inc_start.hour:
        status = "⚠️ WARNING"
        msg    = f"ตรวจจับ pattern ผิดปกติ — อีก {inc_start.hour-h} ชม."
        itype  = incident_type.split("—")[0].strip()
        if "Grid Trip" in itype:   rec = "Pre-charge BESS 90% | Standby Diesel"
        elif "PV Drop" in itype:   rec = "เตรียม Grid import เพิ่ม | Pre-charge BESS"
        elif "Load Spike" in itype: rec = "Discharge BESS เตรียมรับ | เตรียม Diesel"
        else: rec = "เตรียมแผนรับมือ"
    elif inc_end.hour <= h < inc_end.hour+2:
        status = "🔄 RECOVERY"
        msg    = "ระบบกำลัง recover"
        rec    = "Monitor อย่างใกล้ชิด — Re-charge BESS"
    else:
        status = "✅ ปกติ"
        msg    = "ระบบทำงานปกติ"
        rec    = "—"

    timeline_rows.append({
        "ชั่วโมง":  f"{h:02d}:00",
        "สถานะ":   status,
        "สถานการณ์": msg,
        "BESS SOC": f"{soc_icon} {soc:.0f}%",
        "คำแนะนำ Operator": rec,
    })

tl_df = pd.DataFrame(timeline_rows)
def highlight(row):
    if "INCIDENT" in str(row["สถานะ"]):
        return ["background-color: rgba(239,68,68,0.15)"]*len(row)
    elif "WARNING" in str(row["สถานะ"]):
        return ["background-color: rgba(245,158,11,0.12)"]*len(row)
    elif "RECOVERY" in str(row["สถานะ"]):
        return ["background-color: rgba(59,130,246,0.10)"]*len(row)
    return [""]*len(row)

st.dataframe(tl_df.style.apply(highlight, axis=1),
             use_container_width=True, hide_index=True, height=500)
st.caption("⚠️ WARNING = ตรวจจับล่วงหน้า | ⛔ INCIDENT = กำลังเกิด | 🔄 RECOVERY = กำลัง recover")
