import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from shared.synthetic_data import get_site_config

app = FastAPI(title="PEA Optimization API", version="1.0.0")
CONFIG = get_site_config()
COSTS  = CONFIG["costs"]

STRATEGIES = {
    "cost_minimize": {"label":"A — Cost Minimize","grid_w":1.0,"diesel_w":3.5,"bess_w":0.5},
    "bess_protect":  {"label":"B — BESS Protect", "grid_w":1.2,"diesel_w":3.0,"bess_w":5.0},
    "green_first":   {"label":"C — Green First",  "grid_w":2.0,"diesel_w":10.0,"bess_w":0.3},
}

class ForecastPoint(BaseModel):
    datetime: str
    load_kw: float
    pv_kw: float
    net_kw: float

class OptimizeRequest(BaseModel):
    forecast: list[ForecastPoint]
    bess_soc: float = 60.0
    strategy: str = "cost_minimize"

def rule_dispatch(forecast, bess_soc, strategy):
    soc = bess_soc / 100
    cap = CONFIG["bess_capacity_kwh"]
    p_max = CONFIG["bess_power_kw"]
    soc_min, soc_max = 0.20, 0.90
    rows = []
    for f in forecast:
        load   = f["load_kw"]
        pv     = min(f["pv_kw"], load)
        remain = load - pv
        bess_d = bess_c = 0.0
        if strategy in ["cost_minimize","green_first"]:
            if soc > soc_min + 0.05:
                bess_d  = min(remain, p_max, (soc-soc_min)*cap)
                remain -= bess_d
                soc    -= bess_d / cap
        grid   = min(remain, CONFIG["grid_max_kw"])
        remain -= grid
        diesel = max(0, remain)
        h = pd.Timestamp(f["datetime"]).hour
        if h in list(range(0,6))+[23] and strategy != "bess_protect":
            if soc < soc_max - 0.05:
                bess_c = min(p_max, (soc_max-soc)*cap)
                soc   += bess_c / cap
        gc   = COSTS["grid_peak_thb_kwh"] if 9<=h<=21 else COSTS["grid_offpeak_thb_kwh"]
        dc   = COSTS["diesel_thb_liter"] * COSTS["diesel_liter_per_kwh"]
        cost = grid*gc + diesel*dc
        total = pv + bess_d + grid + diesel
        mix  = {"pv":round(pv/load*100,1),"bess":round(bess_d/load*100,1),
                "grid":round(grid/load*100,1),"diesel":round(diesel/load*100,1)} if load>0 else {}
        rows.append({"datetime":f["datetime"],"load_kw":round(load,1),
                     "pv_kw":round(pv,1),"grid_kw":round(grid,1),
                     "bess_kw":round(bess_d-bess_c,1),"diesel_kw":round(diesel,1),
                     "bess_soc_pct":round(soc*100,1),"cost_thb":round(cost,2),"source_mix":mix})
    return rows

@app.get("/optimize/health")
def health():
    return {"status":"ok","strategies":list(STRATEGIES.keys())}

@app.get("/optimize/strategies")
def get_strategies():
    return {"strategies":STRATEGIES}

@app.post("/optimize/schedule")
def optimize(req: OptimizeRequest):
    if req.strategy not in STRATEGIES:
        raise HTTPException(400, f"strategy must be one of {list(STRATEGIES.keys())}")
    fc = [f.dict() for f in req.forecast]
    schedule = rule_dispatch(fc, req.bess_soc, req.strategy)
    total_cost   = sum(h["cost_thb"] for h in schedule)
    total_diesel = sum(h["diesel_kw"] for h in schedule) * COSTS["diesel_liter_per_kwh"]
    total_grid   = sum(h["grid_kw"] for h in schedule)
    total_pv     = sum(h["pv_kw"] for h in schedule)
    co2_kg       = total_diesel * 2.65
    strat        = STRATEGIES[req.strategy]
    return {"generated_at":datetime.now().isoformat(),
            "strategy":req.strategy,"strategy_label":strat["label"],
            "hours":len(schedule),
            "total_cost_thb":round(total_cost,2),
            "total_diesel_liter":round(total_diesel,1),
            "total_grid_kwh":round(total_grid,1),
            "total_pv_kwh":round(total_pv,1),
            "co2_kg":round(co2_kg,1),
            "summary":f"{strat['label']} | ค่าไฟ {total_cost:,.0f} THB | Diesel {total_diesel:.0f}L | CO2 {co2_kg:.0f}kg",
            "schedule":schedule}
