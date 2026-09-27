"""Forecasting and anomaly detection (guide 04).

Pure calculations (postprocessing, baselines, GRU, metrics, anomaly rules, explanations) are kept
separate from offline orchestration (training, selection, calibration, evaluation, registry) and
from database services (`app/services/forecasts.py`, `app/services/analyses.py`).
"""

ENGINE_VERSION = "forecast_engine_v1"
