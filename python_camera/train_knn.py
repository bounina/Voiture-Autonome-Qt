#!/usr/bin/env python3
"""
train_knn.py — Entraîne un classifieur KNN sur les pixels collectés.

Charge pixel_samples.npz (créé par collect_pixels.py),
split 80/20, entraîne un KNN, affiche les métriques,
et sauvegarde le modèle dans knn_model.pkl.

Usage :
    python train_knn.py
    python train_knn.py --k 7
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

SAMPLES_FILE = Path(__file__).parent / "pixel_samples.npz"
MODEL_FILE = Path(__file__).parent / "knn_model.pkl"
RESULTS_DIR = Path(__file__).parent / "knn_results"


def main():
    parser = argparse.ArgumentParser(description="Entraînement KNN")
    parser.add_argument("--k", type=int, default=5, help="Nombre de voisins (default: 5)")
    parser.add_argument("--test-ratio", type=float, default=0.2, help="Ratio test (default: 0.2)")
    args = parser.parse_args()

    # ── Charger les données ──
    if not SAMPLES_FILE.exists():
        print(f"❌ Fichier {SAMPLES_FILE} introuvable !")
        print("   → Lance d'abord : python collect_pixels.py --pi-ip <IP>")
        return 1

    data = np.load(SAMPLES_FILE)
    X, y = data["X"].astype(np.float32), data["y"].astype(np.int32)

    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    print(f"[KNN] Dataset chargé : {n_pos} bleus + {n_neg} sol = {len(X)} pixels")

    if n_pos < 10 or n_neg < 10:
        print("❌ Pas assez de pixels ! Il faut au moins 10 de chaque.")
        return 1

    # ── Split train/test ──
    np.random.seed(42)
    idx = np.random.permutation(len(X))
    split = int(len(X) * (1 - args.test_ratio))
    X_train, X_test = X[idx[:split]], X[idx[split:]]
    y_train, y_test = y[idx[:split]], y[idx[split:]]

    print(f"[KNN] Split : {len(X_train)} train, {len(X_test)} test")

    # ── Entraîner le KNN (OpenCV) ──
    knn = cv2.ml.KNearest_create()
    knn.setDefaultK(args.k)
    knn.setIsClassifier(True)
    knn.train(X_train, cv2.ml.ROW_SAMPLE, y_train)

    print(f"[KNN] Modèle entraîné avec K={args.k}")

    # ── Évaluer sur le set de test ──
    _, y_pred, _, _ = knn.findNearest(X_test, args.k)
    y_pred = y_pred.flatten().astype(np.int32)

    # Matrice de confusion
    tp = int(np.sum((y_pred == 1) & (y_test == 1)))
    fp = int(np.sum((y_pred == 1) & (y_test == 0)))
    fn = int(np.sum((y_pred == 0) & (y_test == 1)))
    tn = int(np.sum((y_pred == 0) & (y_test == 0)))

    accuracy = (tp + tn) / len(y_test) if len(y_test) > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\n{'=' * 50}")
    print(f"  RÉSULTATS DU CLASSIFIEUR KNN (K={args.k})")
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

    # ── Sauvegarder le modèle ──
    knn.save(str(MODEL_FILE.with_suffix(".xml")))
    print(f"\n✅ Modèle sauvegardé : {MODEL_FILE.with_suffix('.xml')}")

    # ── Générer les images de résultats ──
    RESULTS_DIR.mkdir(exist_ok=True)

    # 1. Matrice de confusion visuelle
    conf_img = np.zeros((300, 450, 3), dtype=np.uint8)
    conf_img[:] = (40, 40, 40)

    cv2.putText(conf_img, "MATRICE DE CONFUSION", (80, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    # Headers
    cv2.putText(conf_img, "Predit BLEU", (200, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(conf_img, "Predit SOL", (340, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(conf_img, "Vrai BLEU", (30, 130),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(conf_img, "Vrai SOL", (30, 210),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    # TP (vert)
    cv2.rectangle(conf_img, (190, 90), (310, 160), (0, 130, 0), -1)
    cv2.putText(conf_img, f"TP={tp}", (215, 135),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    # FN (rouge)
    cv2.rectangle(conf_img, (320, 90), (440, 160), (0, 0, 130), -1)
    cv2.putText(conf_img, f"FN={fn}", (345, 135),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    # FP (rouge)
    cv2.rectangle(conf_img, (190, 170), (310, 240), (0, 0, 130), -1)
    cv2.putText(conf_img, f"FP={fp}", (215, 215),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    # TN (vert)
    cv2.rectangle(conf_img, (320, 170), (440, 240), (0, 130, 0), -1)
    cv2.putText(conf_img, f"TN={tn}", (345, 215),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    # Scores en bas
    cv2.putText(conf_img, f"Acc:{accuracy*100:.1f}%  Prec:{precision*100:.1f}%  "
                f"Rec:{recall*100:.1f}%  F1:{f1*100:.1f}%", (20, 280),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)

    conf_path = RESULTS_DIR / "confusion_matrix.png"
    cv2.imwrite(str(conf_path), conf_img)
    print(f"   Matrice de confusion  : {conf_path}")

    # 2. Distribution HSV des classes
    dist_img = np.zeros((300, 400, 3), dtype=np.uint8)
    dist_img[:] = (40, 40, 40)
    cv2.putText(dist_img, "DISTRIBUTION H (Teinte)", (60, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # Histogramme de H pour bleu vs sol
    for label, color, label_name in [(1, (255, 100, 0), "Bleu"), (0, (100, 100, 255), "Sol")]:
        h_vals = X[y == label][:, 0]  # canal H
        hist, _ = np.histogram(h_vals, bins=36, range=(0, 180))
        if hist.max() > 0:
            hist = (hist / hist.max() * 200).astype(int)
        for i, val in enumerate(hist):
            x0 = 20 + i * 10
            cv2.rectangle(dist_img, (x0, 270 - val), (x0 + 8, 270), color, -1)

    cv2.putText(dist_img, "Bleu", (20, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 100, 0), 1)
    cv2.putText(dist_img, "Sol", (100, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 255), 1)
    cv2.putText(dist_img, "H=0", (20, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
    cv2.putText(dist_img, "H=180", (340, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)

    dist_path = RESULTS_DIR / "hsv_distribution.png"
    cv2.imwrite(str(dist_path), dist_img)
    print(f"   Distribution HSV     : {dist_path}")

    # 3. Test avec différentes valeurs de K
    print(f"\n[KNN] Test de K optimal :")
    print(f"  {'K':>3s}  {'Accuracy':>10s}  {'Precision':>10s}  {'Recall':>8s}  {'F1':>6s}")
    print(f"  {'---':>3s}  {'--------':>10s}  {'---------':>10s}  {'------':>8s}  {'--':>6s}")
    for k in [1, 3, 5, 7, 9, 11, 15]:
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
        print(f"  {k:3d}  {t_acc:10.4f}  {t_pre:10.4f}  {t_rec:8.4f}  {t_f1:6.4f}{marker}")

    print(f"\n→ Prochaine étape : python teleop_client.py --pi-ip <IP>  (touche P)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
