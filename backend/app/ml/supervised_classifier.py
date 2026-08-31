import os
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score

MODEL_PATH = "supervised_classifier.pkl"
_model = None

def train_classifier(rows):
    X = np.array([[r["temporal"], r["sentiment"], r["network"], r["lstm"]] for r in rows])
    y = [r["label"] for r in rows]
    if len(set(y)) < 2:
        return None, {"error": "need at least 2 distinct alert types to train"}
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)
    clf = RandomForestClassifier(n_estimators=100, random_state=42)
    clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)
    metrics = {
        "precision": round(precision_score(y_test, y_pred, average="weighted", zero_division=0), 3),
        "recall": round(recall_score(y_test, y_pred, average="weighted", zero_division=0), 3),
        "f1": round(f1_score(y_test, y_pred, average="weighted", zero_division=0), 3),
        "train_size": len(X_train), "test_size": len(X_test),
    }
    joblib.dump(clf, MODEL_PATH)
    global _model
    _model = clf
    return clf, metrics

def load_classifier():
    global _model
    if _model is None and os.path.exists(MODEL_PATH):
        _model = joblib.load(MODEL_PATH)
    return _model

def predict_label(temporal, sentiment, network, lstm):
    clf = load_classifier()
    if clf is None:
        return None
    return clf.predict([[temporal, sentiment, network, lstm]])[0]