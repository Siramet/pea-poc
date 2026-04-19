import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from shared.synthetic_data import generate_load, generate_pv

app = FastAPI(title="PEA Forecast API", version="1.0.0")

_models = {}
_mape_log = {}

def calc_mape(actual, pred):
    mask = actual > 5
    if mask.sum() == 0:
        return 0.0
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)

def add_time_features(df):
    df = df.copy()
    df["hour"] = df["ds"].dt.hour
    df["dow"] = df["ds"].dt.dayofweek
    df["month"] = df["ds"].dt.month
    df["is_peak"] = df["hour"].between(9, 21).astype(int)
    return df

def train_prophet(df_train, target):
    from prophet import Prophet
    cfg = dict(yearly_seasonality=True, daily_seasonality=True, changepoint_prior_scale=0.05)
    if target == "load":
        cfg["weekly_seasonality"] = True
    if target == "pv":
        m = Prophet(growth="logistic", **cfg)
        df_train = df_train.copy()
        df_train["floor"] = 0
        df_train["cap"] = 210
    else:
        m = Prophet(**cfg)
    m.fit(df_train)
    return m

def train_xgboost(df_train):
    from sklearn.ensemble import GradientBoostingRegressor
    df = add_time_features(df_train)
    X = df[["hour","dow","month","is_peak"]].values
    y = df["y"].values
    model = GradientBoostingRegressor(n_estimators=100, max_depth=4, random_state=42)
    model.fit(X, y)
    return model

def predict_prophet(model, future_ds, target):
    if target == "pv":
        future_ds = future_ds.copy()
        future_ds["floor"] = 0
        future_ds["cap"] = 210
    fc = model.predict(future_ds)
    pred = fc["yhat"].values
    if target == "pv":
        pred = np.clip(pred, 0, None)
    return pred

def predict_xgboost(model, future_ds):
    df = add_time_features(future_ds)
    X = df[["hour","dow","month","is_peak"]].values
    return np.clip(model.predict(X), 0, None)

def train_and_select(target):
    df_full = generate_load() if target == "load" else generate_pv()
    split = int(len(df_full) * 0.8)
    df_train = df_full.iloc[:split].copy()
    df_val = df_full.iloc[split:].copy()
    results = {}
    try:
        m_prophet = train_prophet(df_train, target)
        future = df_val[["ds"]].copy()
        if target == "pv":
            future["floor"] = 0
            future["cap"] = 210
        pred_p = predict_prophet(m_prophet, future, target)
        mape_p = calc_mape(df_val["y"].values, pred_p)
        results["prophet"] = {"model": m_prophet, "mape": mape_p}
    except Exception as e:
        print(f"Prophet error: {e}")
    try:
        m_xgb = train_xgboost(df_train)
        pred_x = predict_xgboost(m_xgb, df_val[["ds"]])
        mape_x = calc_mape(df_val["y"].values, pred_x)
        results["xgboost"] = {"model": m_xgb, "mape": mape_x}
    except Exception as e:
        print(f"XGBoost error: {e}")
    if not results:
        raise RuntimeError("All models failed")
    best_name = min(results, key=lambda k: results[k]["mape"])
    best = results[best_name]
    return {"model": best["model"], "model_name": best_name, "mape": round(best["mape"], 2),
            "all_mapes": {k: round(v["mape"], 2) for k, v in results.items()},
            "target": target, "trained_at": datetime.now().isoformat()}

@app.on_event("startup")
async def startup_event():
    print("Training models...")
    for target in ["load", "pv"]:
        result = train_and_select(target)
        _models[target] = result
        _mape_log[target] = result["mape"]
        status = "OK" if result["mape"] <= 10 else "WARN"
        print(f"  [{status}] {target.upper()} — {result['model_name']} MAPE={result['mape']:.1f}%")

class ForecastRequest(BaseModel):
    start_dt: Optional[str] = None
    hours: int = 24

@app.get("/forecast/health")
def health():
    return {"status": "ok", "models": list(_models.keys()), "mape": _mape_log,
            "mape_ok": all(v <= 10 for v in _mape_log.values())}

@app.get("/forecast/mape")
def get_mape():
    if not _models:
        raise HTTPException(503, "Models not ready")
    return {t: {"model_name": i["model_name"], "mape": i["mape"],
                "all_mapes": i["all_mapes"], "mape_ok": i["mape"] <= 10}
            for t, i in _models.items()}

@app.post("/forecast/24h")
def forecast_24h(req: ForecastRequest):
    if not _models:
        raise HTTPException(503, "Models not ready")
    if req.start_dt:
        start = pd.Timestamp(req.start_dt)
    else:
        now = datetime.now()
        start = pd.Timestamp(now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    future_ds = pd.DataFrame({"ds": pd.date_range(start, periods=req.hours, freq="h")})
    load_info = _models["load"]
    if load_info["model_name"] == "prophet":
        load_pred = predict_prophet(load_info["model"], future_ds, "load")
    else:
        load_pred = predict_xgboost(load_info["model"], future_ds)
    pv_info = _models["pv"]
    pv_future = future_ds.copy()
    if pv_info["model_name"] == "prophet":
        pv_pred = predict_prophet(pv_info["model"], pv_future, "pv")
    else:
        pv_pred = predict_xgboost(pv_info["model"], pv_future)
    points = []
    for i, ts in enumerate(future_ds["ds"]):
        lkw = round(float(load_pred[i]), 1)
        pkw = round(float(pv_pred[i]), 1)
        points.append({"datetime": ts.isoformat(), "load_kw": lkw, "pv_kw": pkw, "net_kw": round(lkw-pkw, 1)})
    return {"generated_at": datetime.now().isoformat(), "start_dt": start.isoformat(),
            "hours": req.hours, "load_model": load_info["model_name"], "pv_model": pv_info["model_name"],
            "load_mape": load_info["mape"], "pv_mape": pv_info["mape"],
            "mape_ok": load_info["mape"] <= 10 and pv_info["mape"] <= 10, "forecast": points}
