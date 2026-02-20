# 🚀 Guide de Démarrage — Voiture Autonome SAE

> Ce guide permet à un nouvel utilisateur de reprendre le projet rapidement.

---

## Prérequis

### Matériel
- Raspberry Pi 4 avec Raspberry Pi OS
- Module caméra Pi (CSI) — arrière du véhicule
- LIDAR RPLidar (USB)
- Capteur TFmini (UART)
- Moteur DC avec driver MD04 (I2C, adresse 0x58)
- Servo de direction (PWM GPIO 18)
- PC Windows 10/11

### Logiciels

| Machine | À installer |
|---------|-------------|
| **Raspberry Pi** | Qt5 dev (`qt5-default`), `picamera2`, `opencv-python`, `numpy` |
| **PC Windows** | Python 3.10+, `opencv-python`, `numpy` |

---

## 1. Cloner et compiler

### Sur la Raspberry Pi

```bash
git clone https://github.com/bounina/Voiture-Autonome-Qt.git
cd Voiture-Autonome-Qt

# Compiler le programme C++ Qt
mkdir -p build && cd build
qmake ../sae_sbc.pro
make -j4
```

### Sur le PC Windows

```bash
git clone https://github.com/bounina/Voiture-Autonome-Qt.git
cd Voiture-Autonome-Qt
pip install opencv-python numpy
```

---

## 2. Lancer le système

### Étape 1 — Raspberry Pi (2 terminaux SSH)

```bash
# Terminal 1 : programme C++ (moteurs + commandes)
cd ~/Voiture-Autonome-Qt/build
sudo ./sae_sbc

# Terminal 2 : streaming vidéo
cd ~/Voiture-Autonome-Qt/python_camera
python3 video_streamer.py --rotate 180
```

### Étape 2 — PC Windows

```bash
cd Voiture-Autonome-Qt/python_camera
python teleop_client.py --pi-ip <IP_DE_LA_PI>
```

> 💡 Trouver l'IP de la Pi : `hostname -I` dans un terminal SSH.

### Étape 3 — Piloter !

```
      Z (avancer)
      ↑
 Q ← ─┼─ → D
      ↓
      S (reculer)

 ESPACE = arrêt d'urgence
 O = overlay on/off
 ESC = quitter
```

---

## 3. Calibrer l'overlay de recul

L'overlay de caméra de recul utilise un trapèze que tu peux ajuster visuellement :

```bash
python python_camera/calibrate_overlay.py --pi-ip <IP_DE_LA_PI>
```

1. Une fenêtre s'ouvre avec une capture de la caméra
2. Déplace les **4 coins** du trapèze à la souris
3. Appuie sur **Entrée** pour sauvegarder → crée `overlay_calib.json`
4. Relance `teleop_client.py`, l'overlay suit ta calibration

---

## 4. Structure des fichiers

```
Voiture-Autonome-Qt/
│
├── 📄 C++ (Raspberry Pi — programme embarqué)
│   ├── controleur.cpp/h       → Boucle PID + téléopération manuelle
│   ├── materielreel.cpp/h     → Pilotage moteur (I2C) et servo (PWM)
│   ├── serveurtcp.cpp/h       → Réception commandes TCP port 8884
│   ├── servomoteur.cpp/h      → Contrôle PWM du servo direction
│   ├── pwm.cpp/h              → Accès sysfs PWM Linux
│   ├── tfmini.cpp/h           → Capteur distance frontal
│   └── mainwindow.cpp/h       → Interface Qt + câblage signaux/slots
│
├── 🐍 python_camera/ (scripts Python)
│   ├── video_streamer.py      → [PI] Serveur streaming JPEG-over-TCP
│   ├── teleop_client.py       → [PC] Client téléop + overlay + HUD
│   ├── calibrate_overlay.py   → [PC] Calibration interactive du trapèze
│   ├── calibrate_parking.py   → [PC] Calibration distances (ancien)
│   ├── overlay_calib.json     → Positions des 4 coins du trapèze
│   ├── parking_calib.json     → Calibration distances (ancien)
│   └── test_servo_gpio.py     → [PI] Diagnostic PWM
│
├── 📝 Documentation
│   ├── README.md              → Documentation principale
│   ├── GUIDE_DEMARRAGE.md     → Ce fichier
│   └── RESUME_ARCHITECTURE.txt → Architecture technique détaillée
│
└── sae_sbc.pro                → Fichier projet Qt
```

---

## 5. Configuration matérielle (Raspberry Pi)

### /boot/firmware/config.txt

```ini
dtparam=i2c_arm=on
dtoverlay=pwm-2chan,pin=18,func=2,pin2=19,func2=2
```

### Brochage

| Broche | GPIO | Fonction |
|--------|------|----------|
| Pin 12 | GPIO 18 | PWM0 → Servo direction |
| Pin 3/5 | SDA1/SCL1 | I2C → Moteur MD04 (addr 0x58) |
| USB | — | LIDAR RPLidar |
| UART | — | TFmini |
| CSI | — | Picamera2 |

---

## 6. Passer en mode autonome

Le mode téléopération est actif par défaut. Pour réactiver le **mode autonome PID** :

Dans `controleur.h`, changer :
```cpp
bool modeManuel{true};   →   bool modeManuel{false};
```

Recompiler et relancer. Le LIDAR guidera la voiture automatiquement.

---

## 7. Dépannage

| Symptôme | Solution |
|----------|----------|
| `[VIDEO] Waiting...` | Vérifier que `video_streamer.py` tourne sur la Pi |
| `[CMD] Could not connect` | Vérifier que `sudo ./sae_sbc` tourne sur la Pi |
| Servo ne bouge pas | Vérifier `dtoverlay=pwm-2chan,pin=18` dans config.txt |
| Moteur ne démarre pas | Vérifier I2C : `i2cdetect -y 1` (doit voir 0x58) |
| Overlay mal positionné | Relancer `calibrate_overlay.py` |
