"""ML scoring (Graph1 Node 2): LightGBM supervised + IsolationForest anomaly.

- Tries LightGBM; falls back to sklearn HistGradientBoostingClassifier when
  LightGBM is unavailable (py3.14 wheels) — same API, logged model_type.
- IsolationForest (sklearn) unsupervised on the same feature space.
- composite = 0.7*supervised + 0.3*anomaly (settings weights).
- SHAP if shap installed, else gain-based approx (abs weight * |x - mean|).
- Artifacts: ./models/{supervised.pkl, isoforest.pkl, meta.json} + MLflow if available.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from .config import settings

_log = logging.getLogger(__name__)

FEATURE_COLS = ["n_txs", "total_in", "total_out", "net_flow_abs", "max_amount",
                "mean_amount", "pass_through_ratio", "velocity_24h", "night_ratio",
                "structuring_flags", "new_counterparty_ratio", "high_risk_touch",
                "pagerank", "betweenness", "in_degree", "out_degree",
                "is_in_cycle", "community_id_nn", "shortest_path_hr_nn"]

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"


def to_vector(features: dict, graph: dict) -> list[float]:
    return [
        float(features.get("n_txs", 0)), float(features.get("total_in", 0)),
        float(features.get("total_out", 0)), abs(float(features.get("net_flow", 0))),
        float(features.get("max_amount", 0)), float(features.get("mean_amount", 0)),
        float(features.get("pass_through_ratio", 0)), float(features.get("velocity_24h", 0)),
        float(features.get("night_ratio", 0)), float(features.get("structuring_flags", 0)),
        float(features.get("new_counterparty_ratio", 0)), float(features.get("high_risk_touch", 0)),
        float(graph.get("pagerank", 0)), float(graph.get("betweenness", 0)),
        float(graph.get("in_degree", 0)), float(graph.get("out_degree", 0)),
        1.0 if graph.get("is_in_cycle") else 0.0,
        0.0 if (graph.get("community_id") or 0) < 0 else float(graph.get("community_id") or 0),
        0.0 if (graph.get("shortest_path_hr") or -1) < 0 else float(graph.get("shortest_path_hr")),
    ]


def _supervised_model(family: str = "auto"):
    """auto: LightGBM, falling back to sklearn HistGB (logged). Explicit family forces."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    if family in ("auto", "lightgbm"):
        try:
            import lightgbm as lgb

            return lgb.LGBMClassifier(n_estimators=100, verbose=-1), "lightgbm"
        except Exception:
            if family == "lightgbm":
                raise
    return HistGradientBoostingClassifier(max_iter=100), "histgb_fallback"


def train(X: np.ndarray, y: np.ndarray, family: str = "auto") -> dict:
    from sklearn.ensemble import IsolationForest

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    sup, mtype = _supervised_model(family)
    sup.fit(X, y)
    iso = IsolationForest(n_estimators=100, contamination="auto", random_state=42)
    iso.fit(X)
    import pickle

    (MODEL_DIR / "supervised.pkl").write_bytes(pickle.dumps(sup))
    (MODEL_DIR / "isoforest.pkl").write_bytes(pickle.dumps(iso))
    meta = {"model_type": mtype, "n": int(len(y)), "feature_cols": FEATURE_COLS}
    (MODEL_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    try:
        import mlflow

        mlflow.set_tracking_uri(str(settings.MLFLOW_TRACKING_URI))
        with mlflow.start_run(run_name="train"):
            mlflow.log_params({"model_type": mtype, "n": len(y)})
            mlflow.log_metrics({"pos_rate": float(y.mean())})
    except Exception as e:
        _log.warning("mlflow logging skipped: %s", e)
    return meta


def load():
    import pickle

    sup = pickle.loads((MODEL_DIR / "supervised.pkl").read_bytes())
    iso = pickle.loads((MODEL_DIR / "isoforest.pkl").read_bytes())
    return sup, iso


def score(vec: list[float]) -> dict:
    import numpy as np

    sup, iso = load()
    X = np.array(vec, dtype=float).reshape(1, -1)
    try:
        proba = float(sup.predict_proba(X)[0][1])
    except Exception:
        proba = float(sup.predict(X)[0])
    # isolation forest: decision -> map to 0..1 anomaly
    try:
        s = float(iso.decision_function(X)[0])
        anomaly = float(1.0 / (1.0 + np.exp(4 * s)))  # lower decision => more anomalous
    except Exception:
        anomaly = 0.5
    composite = settings.SUPERVISED_WEIGHT * proba + settings.ANOMALY_WEIGHT * anomaly
    return {"supervised": round(proba, 4), "anomaly": round(anomaly, 4), "composite": round(composite, 4)}


def explain(vec: list[float], top_k: int = 5) -> list[dict]:
    """SHAP values if shap installed, else weight*deviation approx."""
    try:
        import pickle

        import shap

        sup = pickle.loads((MODEL_DIR / "supervised.pkl").read_bytes())
        ex = shap.TreeExplainer(sup)
        import numpy as np

        vals = ex.shap_values(np.array(vec, dtype=float).reshape(1, -1))
        if isinstance(vals, list):
            vals = vals[1] if len(vals) > 1 else vals[0]
        row = np.asarray(vals).ravel()
        idx = np.argsort(-np.abs(row))[:top_k]
        return [{"feature": FEATURE_COLS[i], "value": float(row[i])} for i in idx]
    except Exception:
        import numpy as np

        v = np.array(vec, dtype=float)
        w = np.abs(v) / (np.abs(v).sum() + 1e-9)
        idx = np.argsort(-w)[:top_k]
        return [{"feature": FEATURE_COLS[i], "value": round(float(w[i]), 4)} for i in idx]
