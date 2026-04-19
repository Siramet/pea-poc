import pandas as pd
import numpy as np

SITE = {
    "name": "PEA Demo Site",
    "load_peak_kw": 500,
    "pv_capacity_kw": 200,
    "bess_capacity_kwh": 400,
    "bess_power_kw": 100,
    "diesel_rated_kw": 300,
    "grid_max_kw": 600,
}

COSTS = {
    "grid_peak_thb_kwh": 5.20,
    "grid_offpeak_thb_kwh": 2.60,
    "diesel_thb_liter": 32.0,
    "diesel_liter_per_kwh": 0.35,
    "bess_degradation_thb_cycle": 1000.0,
}

def generate_load(start="2023-01-01", periods=8760):
    rng = pd.date_range(start, periods=periods, freq="h")
    hour = rng.hour
    dow = rng.dayofweek
    base = (120 + 250*np.exp(-((hour-13)**2)/18) + 80*np.exp(-((hour-9)**2)/10) - 60*(dow>=5))
    np.random.seed(42)
    noise = np.random.normal(0, 15, periods)
    seasonal = 30*np.sin(2*np.pi*np.arange(periods)/8760)
    load = np.clip(base+noise+seasonal, 80, SITE["load_peak_kw"])
    return pd.DataFrame({"ds": rng, "y": load.round(1)})

def generate_pv(start="2023-01-01", periods=8760):
    rng = pd.date_range(start, periods=periods, freq="h")
    hour = rng.hour
    doy = rng.dayofyear
    solar_angle = np.maximum(0, np.sin(np.pi*(hour-6)/12))
    seasonal = 0.85 + 0.15*np.cos(2*np.pi*(doy-30)/365)
    np.random.seed(7)
    cloud_factor = np.random.beta(5, 2, periods)
    pv = SITE["pv_capacity_kw"]*solar_angle*seasonal*cloud_factor
    pv = np.clip(pv.round(1), 0, SITE["pv_capacity_kw"])
    return pd.DataFrame({"ds": rng, "y": pv})

def get_bess_initial_state():
    return {"soc_percent": 60.0, "capacity_kwh": SITE["bess_capacity_kwh"],
            "power_kw": SITE["bess_power_kw"], "soc_min": 20.0, "soc_max": 90.0}

def get_site_config():
    return {**SITE, "costs": COSTS}
