import streamlit as st
import pandas as pd
import numpy as np
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

st.set_page_config(page_title="Diesel Tank Manager", layout="wide", page_icon="⛽")

from shared.synthetic_data import get_site_config, generate_load
from module2_optimization.app import rule_dispatch, COSTS

CONFIG = get_site_config()

# ── Persistent storage (session state) ────────────────────────────────────
if "tanks" not in st.session_state:
    st.session_state.tanks = [
        {"id": 1, "name": "Tank A", "capacity_L": 10000, "current_L": 3240},
    ]
if "refill_history" not in st.session_state:
    st.session_state.refill_history = [
        {"date": "2026-03-15", "tank": "Tank A", "volume_L": 5000,
         "price_per_L": 31.00, "supplier": "PTT"},
        {"date": "2026-04-01", "tank": "Tank A", "volume_L": 3000,
         "price_per_L": 32.50, "supplier": "PTT"},
    ]

# ── Helper functions ───────────────────────────────────────────────────────
def weighted_avg_price(history):
    if not history:
        return 0
    total_vol  = sum(h["volume_L"] for h in history)
    total_cost = sum(h["volume_L"] * h["price_per_L"] for h in history)
    return total_cost / total_vol if total_vol > 0 else 0

def forecast_daily_diesel(days=7, strategy="cost_minimize", bess_soc=60):
    today = pd.Timestamp.now().floor("h")
    daily = []
    for d in range(days):
        date = today + pd.Timedelta(days=d)
        load_df = generate_load(str(date.date()), 24)
        pv_df   = __import__('shared.synthetic_data',
                  fromlist=['generate_pv']).generate_pv(str(date.date()), 24)
        fc = [{"datetime": str(load_df["ds"].iloc[i]),
               "load_kw": round(float(load_df["y"].iloc[i]), 1),
               "pv_kw":   round(float(pv_df["y"].iloc[i]), 1),
               "net_kw":  round(float(load_df["y"].iloc[i] - pv_df["y"].iloc[i]), 1)}
              for i in range(24)]
        sch = rule_dispatch(fc, bess_soc, strategy)
        diesel_kwh = sum(h["diesel_kw"] for h in sch)
        diesel_L   = diesel_kwh * COSTS["diesel_liter_per_kwh"]
        daily.append({"date": date.date(), "diesel_L": round(diesel_L, 1),
                      "diesel_kwh": round(diesel_kwh, 1)})
    return daily

# ── Sidebar settings ───────────────────────────────────────────────────────
with st.sidebar:
    st.title("⛽ Diesel Manager")
    st.divider()
    strategy = st.selectbox("กลยุทธ์",
        ["cost_minimize","bess_protect","green_first"],
        format_func=lambda x: {"cost_minimize":"A — Cost Minimize",
                                "bess_protect": "B — BESS Protect",
                                "green_first":  "C — Green First"}[x])
    bess_soc = st.slider("BESS SOC (%)", 20, 90, 60)
    warn_pct = st.slider("Warning level (%)", 10, 40, 25)
    st.divider()
    st.caption("ข้อมูลถังจะ reset เมื่อ restart app")
    st.caption("Production: ใช้ database จริง")

# ── Page title ─────────────────────────────────────────────────────────────
st.title("⛽ Diesel Tank Manager")
st.caption("ติดตามปริมาตร คาดการณ์การใช้ และบริหารต้นทุนเชื้อเพลิง")

# ── Forecast ───────────────────────────────────────────────────────────────
with st.spinner("คำนวณ forecast..."):
    forecast_days = forecast_daily_diesel(7, strategy, bess_soc)

# ── Weighted avg price ─────────────────────────────────────────────────────
wav_price = weighted_avg_price(st.session_state.refill_history)
latest_price = (st.session_state.refill_history[-1]["price_per_L"]
                if st.session_state.refill_history else 32.0)

# ── Summary metrics ────────────────────────────────────────────────────────
total_current = sum(t["current_L"] for t in st.session_state.tanks)
total_capacity = sum(t["capacity_L"] for t in st.session_state.tanks)
total_pct = total_current / total_capacity * 100 if total_capacity > 0 else 0
daily_avg = np.mean([d["diesel_L"] for d in forecast_days])

days_left = total_current / daily_avg if daily_avg > 0 else 999
refill_date = pd.Timestamp.now() + pd.Timedelta(days=days_left)
refill_volume_rec = max(0, total_capacity * 0.8 - total_current)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("ปริมาตรรวม",
          f"{total_current:,.0f} L",
          f"{total_pct:.0f}% ของถัง")
m2.metric("ราคาเฉลี่ย (weighted)",
          f"฿{wav_price:.2f}/L",
          f"ล่าสุด ฿{latest_price:.2f}/L")
m3.metric("ใช้เฉลี่ย/วัน (forecast)",
          f"{daily_avg:.0f} L",
          f"฿{daily_avg*wav_price:,.0f}/วัน")
m4.metric("เหลือพอใช้",
          f"{days_left:.0f} วัน",
          delta="ต้องเติมเร็ว" if days_left < 7 else "ปกติ",
          delta_color="inverse" if days_left < 7 else "normal")
m5.metric("ควรเติมภายใน",
          refill_date.strftime("%d %b %Y"),
          f"แนะนำ {refill_volume_rec:,.0f} L")

st.divider()

# ── Tank gauges + Add tank ─────────────────────────────────────────────────
st.subheader("สถานะถังดีเซล")

col_tanks = st.columns(len(st.session_state.tanks) + 1)

for idx, tank in enumerate(st.session_state.tanks):
    pct = tank["current_L"] / tank["capacity_L"] * 100
    with col_tanks[idx]:
        st.markdown(f"**{tank['name']}**")
        color = "🔴" if pct < warn_pct else "🟡" if pct < 40 else "🟢"
        st.progress(pct/100, text=f"{color} {pct:.0f}% ({tank['current_L']:,} L)")
        st.caption(f"capacity: {tank['capacity_L']:,} L")

        with st.expander("แก้ไขถัง"):
            new_cap = st.number_input(f"Capacity (L)", 1000, 50000,
                                       tank["capacity_L"], 1000,
                                       key=f"cap_{idx}")
            new_cur = st.number_input(f"ปริมาตรปัจจุบัน (L)", 0,
                                       new_cap, tank["current_L"], 100,
                                       key=f"cur_{idx}")
            new_name = st.text_input("ชื่อถัง", tank["name"], key=f"name_{idx}")
            if st.button("บันทึก", key=f"save_{idx}"):
                st.session_state.tanks[idx]["capacity_L"] = new_cap
                st.session_state.tanks[idx]["current_L"] = new_cur
                st.session_state.tanks[idx]["name"] = new_name
                st.rerun()

with col_tanks[-1]:
    st.markdown("**เพิ่มถังใหม่**")
    with st.expander("+ เพิ่มถัง"):
        new_name = st.text_input("ชื่อถัง", f"Tank {chr(65+len(st.session_state.tanks))}")
        new_cap  = st.number_input("Capacity (L)", 1000, 50000, 10000, 1000)
        new_cur  = st.number_input("ปริมาตรเริ่มต้น (L)", 0, new_cap, 5000, 100)
        if st.button("เพิ่มถัง"):
            st.session_state.tanks.append({
                "id": len(st.session_state.tanks)+1,
                "name": new_name,
                "capacity_L": new_cap,
                "current_L": new_cur
            })
            st.rerun()

st.divider()

# ── Forecast chart ─────────────────────────────────────────────────────────
st.subheader("Forecast การใช้ Diesel 7 วันข้างหน้า")

fc_df = pd.DataFrame(forecast_days).set_index("date")
fc_df["cost_thb"] = (fc_df["diesel_L"] * wav_price).round(0)

col_fc1, col_fc2 = st.columns(2)
with col_fc1:
    st.caption("ปริมาณ (ลิตร/วัน)")
    st.bar_chart(fc_df[["diesel_L"]], color=["#EF9F27"])
with col_fc2:
    st.caption("ต้นทุน (฿/วัน)")
    st.bar_chart(fc_df[["cost_thb"]], color=["#E24B4A"])

# Cumulative depletion
st.caption("ระดับถังที่คาดการณ์ (รวมทุกถัง)")
levels = []
remaining = total_current
for d in forecast_days:
    remaining = max(0, remaining - d["diesel_L"])
    levels.append({"date": d["date"], "เหลือ (L)": round(remaining, 0),
                   "warning": total_capacity * warn_pct / 100})
level_df = pd.DataFrame(levels).set_index("date")
st.line_chart(level_df, color=["#EF9F27","#E24B4A"])

if days_left < 7:
    st.error(f"⛔ ปริมาตรจะถึง warning level ใน {days_left:.0f} วัน ({refill_date.strftime('%d %b')})"
             f" — แนะนำเติม {refill_volume_rec:,.0f} L ราคาประมาณ ฿{refill_volume_rec*latest_price:,.0f}")
elif days_left < 14:
    st.warning(f"⚠️ ควรวางแผนเติม Diesel ภายใน {refill_date.strftime('%d %b %Y')}")
else:
    st.success(f"✅ ปริมาตรเพียงพอ — ถัดไปควรเติมประมาณ {refill_date.strftime('%d %b %Y')}")

st.divider()

# ── Refill form ────────────────────────────────────────────────────────────
st.subheader("บันทึกการเติม Diesel")

with st.form("refill_form"):
    r1, r2, r3, r4, r5 = st.columns(5)
    with r1:
        r_date = st.date_input("วันที่เติม", value=pd.Timestamp.now())
    with r2:
        r_tank = st.selectbox("ถัง", [t["name"] for t in st.session_state.tanks])
    with r3:
        r_vol  = st.number_input("ปริมาณ (L)", 100, 50000, 5000, 100)
    with r4:
        r_price = st.number_input("ราคา/ลิตร (฿)", 20.0, 50.0, latest_price, 0.01)
    with r5:
        r_supplier = st.text_input("ผู้จำหน่าย", "PTT")

    submitted = st.form_submit_button("บันทึกการเติม")
    if submitted:
        st.session_state.refill_history.append({
            "date": str(r_date), "tank": r_tank,
            "volume_L": r_vol, "price_per_L": r_price,
            "supplier": r_supplier
        })
        for t in st.session_state.tanks:
            if t["name"] == r_tank:
                t["current_L"] = min(t["capacity_L"], t["current_L"] + r_vol)
        st.success(f"บันทึกแล้ว — เติม {r_vol:,} L ที่ ฿{r_price:.2f}/L = ฿{r_vol*r_price:,.0f}")
        st.rerun()

st.divider()

# ── Refill history + weighted cost ────────────────────────────────────────
st.subheader("ประวัติการเติมและต้นทุนเฉลี่ย (Weighted Average Cost)")

hist_df = pd.DataFrame(st.session_state.refill_history)
if not hist_df.empty:
    hist_df["total_cost"] = hist_df["volume_L"] * hist_df["price_per_L"]
    hist_df["weighted_avg"] = hist_df["total_cost"].cumsum() / hist_df["volume_L"].cumsum()
    hist_df = hist_df.rename(columns={
        "date":"วันที่", "tank":"ถัง", "volume_L":"ปริมาณ (L)",
        "price_per_L":"ราคา/L (฿)", "supplier":"ผู้จำหน่าย",
        "total_cost":"ค่าใช้จ่าย (฿)", "weighted_avg":"ราคาเฉลี่ย WAC (฿/L)"
    })
    st.dataframe(hist_df.set_index("วันที่"), use_container_width=True)

    wav = weighted_avg_price(st.session_state.refill_history)
    total_spent = sum(h["volume_L"]*h["price_per_L"]
                      for h in st.session_state.refill_history)
    c1, c2, c3 = st.columns(3)
    c1.metric("Weighted Avg Cost", f"฿{wav:.2f}/L")
    c2.metric("ค่าใช้จ่ายรวม (ประวัติ)", f"฿{total_spent:,.0f}")
    c3.metric("ปริมาณรวมที่เติม",
              f"{sum(h['volume_L'] for h in st.session_state.refill_history):,} L")
