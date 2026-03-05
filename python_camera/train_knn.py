#!/usr/bin/env python3
"""
train_knn.py — Entraîne un classifieur KNN sur les pixels collectés (6D: HSV+LAB).

Charge pixel_samples.npz, split 80/20, entraîne un KNN,
affiche les métriques, et sauvegarde le modèle dans knn_model.xml.

Usage :
    python train_knn.py
    python train_knn.py --k 7
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

SAMPLES_FILE = Path(__file__).parent / "pixel_samples.npz"
MODEL_FILE = Path(__file__).parent / "knn_model.xml"
RESULTS_DIR = Path(__file__).parent / "knn_results"


def main():
    parser = argparse.ArgumentParser(description="Entraînement KNN")
    parser.add_argument("--k", type=int, default=5, help="Nombre de voisins (default: 5)")
    parser.add_argument("--test-ratio", type=float, default=0.2)
    args = parser.parse_args()

    if not SAMPLES_FILE.exists():
        print(f"❌ Fichier {SAMPLES_FILE} introuvable !")
        print("   → Lance d'abord : python collect_pixels.py --pi-ip <IP>")
        return 1

    data = np.load(SAMPLES_FILE)
    X, y = data["X"].astype(np.float32), data["y"].astype(np.int32)

    n_features = X.shape[1]
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    print(f"[KNN] Dataset : {n_pos} bleus + {n_neg} sol = {len(X)} pixels ({n_features}D)")

    if n_features == 3:
        print("⚠ Ancien format 3D (HSV seul). Relance collect_pixels.py pour le nouveau format 6D (HSV+LAB).")
        return 1

    if n_pos < 10 or n_neg < 10:
        print("❌ Pas assez de pixels ! Il faut au moins 10 de chaque.")
        return 1

    # ── Sous-échantillonner pour la vitesse ──
    # KNN calcule la distance à TOUS les points → 300 max suffit largement
    MAX_PER_CLASS = 150
    np.random.seed(42)
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    if len(pos_idx) > MAX_PER_CLASS:
        pos_idx = np.random.choice(pos_idx, MAX_PER_CLASS, replace=False)
    if len(neg_idx) > MAX_PER_CLASS:
        neg_idx = np.random.choice(neg_idx, MAX_PER_CLASS, replace=False)
    keep = np.concatenate([pos_idx, neg_idx])
    X, y = X[keep], y[keep]
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    print(f"[KNN] Sous-échantillonné → {n_pos} bleus + {n_neg} sol = {len(X)} pixels")

    # ── Normalisation ──
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_std[X_std == 0] = 1.0
    X_norm = (X - X_mean) / X_std

    np.savez(SAMPLES_FILE.parent / "knn_norm.npz", mean=X_mean, std=X_std)

    # ── Split train/test ──
    np.random.seed(42)
    idx = np.random.permutation(len(X_norm))
    split = int(len(X_norm) * (1 - args.test_ratio))
    X_train, X_test = X_norm[idx[:split]], X_norm[idx[split:]]
    y_train, y_test = y[idx[:split]], y[idx[split:]]

    print(f"[KNN] Split : {len(X_train)} train, {len(X_test)} test")

    # ── Entraîner le KNN ──
    knn = cv2.ml.KNearest_create()
    knn.setDefaultK(args.k)
    knn.setIsClassifier(True)
    knn.train(X_train, cv2.ml.ROW_SAMPLE, y_train)

    print(f"[KNN] Modèle entraîné avec K={args.k} ({n_features} features)")

    # ── Évaluer ──
    _, y_pred, _, _ = knn.findNearest(X_test, args.k)
    y_pred = y_pred.flatten().astype(np.int32)

    tp = int(np.sum((y_pred == 1) & (y_test == 1)))
    fp = int(np.sum((y_pred == 1) & (y_test == 0)))
    fn = int(np.sum((y_pred == 0) & (y_test == 1)))
    tn = int(np.sum((y_pred == 0) & (y_test == 0)))

    accuracy = (tp + tn) / len(y_test) if len(y_test) > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\n{'=' * 50}")
    print(f"  RÉSULTATS KNN K={args.k} — {n_features} features (HSV+LAB)")
    print(f"{'=' * 50}")
    print(f"\n  Matrice de confusion :")
    print(f"                    Prédit BLEU   Prédit SOL")
    print(f"  Vrai BLEU     :      {tp:5d}        {fn:5d}")
    print(f"  Vrai SOL      :      {fp:5d}        {tn:5d}")
    print(f"\n  Accuracy  : {accuracy:.4f}  ({accuracy*100:.1f}%)")
    print(f"  Précision : {precision:.4f}  ({precision*100:.1f}%)")
    print(f"  Rappel    : {recall:.4f}  ({recall*100:.1f}%)")
    print(f"  F1-score  : {f1:.4f}  ({f1*100:.1f}%)")
    print(f"{'=' * 50}")

    # ── Sauvegarder ──
    knn.save(str(MODEL_FILE))
    print(f"\n✅ Modèle KNN sauvegardé : {MODEL_FILE}")

    # ── Calculer les seuils automatiques (FAST mode) ──
    # Comme les classes sont parfaitement séparables, on peut utiliser
    # cv2.inRange() à pleine résolution au lieu du KNN (1000× plus rapide)
    pos_data = data["X"][data["y"] == 1].astype(np.float32)  # données NON sous-échantillonnées
    # Colonnes: H,S,V,L,a,b
    channel_names = ["H", "S", "V", "L", "a", "b"]
    thresholds = {}
    print(f"\n[FAST] Seuils automatiques calculés à partir de {len(pos_data)} pixels bleus :")
    for i, name in enumerate(channel_names):
        vals = pos_data[:, i]
        mean = float(np.mean(vals))
        std = float(np.std(vals))
        # Utiliser mean ± 2.5*std pour capturer 98.8% des pixels bleus
        lo = max(0, mean - 2.5 * std)
        hi = min(255, mean + 2.5 * std)
        thresholds[f"{name}_min"] = round(lo)
        thresholds[f"{name}_max"] = round(hi)
        print(f"   {name}: {lo:.0f} - {hi:.0f}  (mean={mean:.1f} std={std:.1f})")

    thresholds_file = SAMPLES_FILE.parent / "knn_thresholds.json"
    with open(thresholds_file, "w") as f:
        json.dump(thresholds, f, indent=2)
    print(f"✅ Seuils sauvegardés : {thresholds_file}")
    print(f"   → parking_detector.py utilisera inRange() à pleine résolution (FAST)")

    # ── Résultats visuels ──
    RESULTS_DIR.mkdir(exist_ok=True)

    # Matrice de confusion
    conf_img = np.zeros((300, 450, 3), dtype=np.uint8)
    conf_img[:] = (40, 40, 40)
    cv2.putText(conf_img, "MATRICE DE CONFUSION", (80, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    cv2.putText(conf_img, "Predit BLEU", (200, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(conf_img, "Predit SOL", (340, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(conf_img, "Vrai BLEU", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(conf_img, "Vrai SOL", (30, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    cv2.rectangle(conf_img, (190, 90), (310, 160), (0, 130, 0), -1)
    cv2.putText(conf_img, f"TP={tp}", (215, 135), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.rectangle(conf_img, (320, 90), (440, 160), (0, 0, 130), -1)
    cv2.putText(conf_img, f"FN={fn}", (345, 135), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.rectangle(conf_img, (190, 170), (310, 240), (0, 0, 130), -1)
    cv2.putText(conf_img, f"FP={fp}", (215, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.rectangle(conf_img, (320, 170), (440, 240), (0, 130, 0), -1)
    cv2.putText(conf_img, f"TN={tn}", (345, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    cv2.putText(conf_img, f"Acc:{accuracy*100:.1f}%  Prec:{precision*100:.1f}%  "
                f"Rec:{recall*100:.1f}%  F1:{f1*100:.1f}%", (20, 280),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)

    cv2.imwrite(str(RESULTS_DIR / "confusion_matrix.png"), conf_img)

    # Distribution du canal LAB-b (le plus discriminant)
    dist_img = np.zeros((300, 400, 3), dtype=np.uint8)
    dist_img[:] = (40, 40, 40)
    cv2.putText(dist_img, "DISTRIBUTION LAB-b (bleu vs gris)", (30, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

    for label, color, lbl in [(1, (255, 100, 0), "Bleu"), (0, (100, 100, 255), "Sol")]:
        b_vals = X[y == label][:, 5]  # canal LAB-b = index 5
        hist, _ = np.histogram(b_vals, bins=50, range=(0, 255))
        if hist.max() > 0:
            hist = (hist / hist.max() * 200).astype(int)
        for i, val in enumerate(hist):
            x0 = 20 + i * 7
            cv2.rectangle(dist_img, (x0, 260 - val), (x0 + 5, 260), color, -1)

    cv2.putText(dist_img, "Bleu", (20, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 100, 0), 1)
    cv2.putText(dist_img, "Sol", (100, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 255), 1)
    cv2.putText(dist_img, "b=0 (bleu)", (20, 275), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
    cv2.putText(dist_img, "b=255 (jaune)", (290, 275), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
    cv2.imwrite(str(RESULTS_DIR / "lab_b_distribution.png"), dist_img)

    print(f"   Matrice de confusion : {RESULTS_DIR / 'confusion_matrix.png'}")
    print(f"   Distribution LAB-b  : {RESULTS_DIR / 'lab_b_distribution.png'}")

    # Test K optimal
    print(f"\n[KNN] Test de K optimal :")
    print(f"  {'K':>3s}  {'Acc':>8s}  {'Prec':>8s}  {'Rec':>8s}  {'F1':>6s}")
    for k in [1, 3, 5, 7, 9, 11]:
        knn_test = cv2.ml.KNearest_create()
        knn_test.setDefaultK(k)
        knn_test.setIsClassifier(True)
        knn_test.train(X_train, cv2.ml.ROW_SAMPLE, y_train)
        _, pred, _, _ = knn_test.findNearest(X_test, k)
        pred = pred.flatten().astype(np.int32)

        t_tp = int(np.sum((pred == 1) & (y_test == 1)))
        t_fp = int(np.sum((pred == 1) & (y_test == 0)))
        t_fn = int(np.sum((pred == 0) & (y_test == 1)))
        t_tn = int(np.sum((pred == 0) & (y_test == 0)))
        t_acc = (t_tp + t_tn) / len(y_test)
        t_pre = t_tp / (t_tp + t_fp) if (t_tp + t_fp) > 0 else 0
        t_rec = t_tp / (t_tp + t_fn) if (t_tp + t_fn) > 0 else 0
        t_f1 = 2 * t_pre * t_rec / (t_pre + t_rec) if (t_pre + t_rec) > 0 else 0
        marker = " ◄" if k == args.k else ""
        print(f"  {k:3d}  {t_acc:8.4f}  {t_pre:8.4f}  {t_rec:8.4f}  {t_f1:6.4f}{marker}")

    print(f"\n→ Prochaine étape : python teleop_client.py --pi-ip <IP>  (touche P)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
