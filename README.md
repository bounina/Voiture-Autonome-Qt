# 🏎️ Voiture Autonome — Projet SAE

> Système de voiture autonome miniature basé sur Raspberry Pi 4 avec téléopération temps réel et conduite autonome par LIDAR/PID.

---

## 📋 Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Architecture système](#architecture-système)
- [Communication réseau](#communication-réseau)
- [Téléopération RC](#téléopération-rc)
- [Chaîne de commande matérielle](#chaîne-de-commande-matérielle)
- [Mode autonome PID](#mode-autonome-pid)
- [Configuration matérielle](#configuration-matérielle)
- [Installation](#installation)
- [Mode d'emploi](#mode-demploi)
- [Structure des dépôts](#structure-des-dépôts)
- [Problèmes résolus](#problèmes-résolus)
- [Workflow Git](#workflow-git)

---

## Vue d'ensemble

Ce projet implémente un véhicule autonome miniature capable de :

1. **Téléopération RC** — Pilotage temps réel depuis un PC distant avec retour vidéo (~30 FPS) et contrôles simultanés (accélérer + tourner)
2. **Conduite autonome** — Suivi de murs via LIDAR 360° et contrôleur PID (code préservé, désactivable)
3. **Calibration** — Projection d'une zone de stationnement par homographie

| Machine | Rôle | OS |
|---------|------|----|
| **Raspberry Pi 4** | Cerveau embarqué (C++ Qt) + caméra + capteurs | Raspberry Pi OS |
| **PC Windows** | Interface opérateur (vidéo + clavier) | Windows 10/11 |

Connexion via **WiFi local** ou **Tailscale VPN** (pilotage à distance depuis n'importe quel réseau).

---

## Architecture système

```
┌────────────────── RASPBERRY PI 4 ──────────────────────┐
│                                                         │
│  ┌────────┐  ┌────────┐  ┌──────────┐                 │
│  │ LIDAR  │  │ TFmini │  │Picamera2 │                 │
│  │RPLidar │  │ (dist.)│  │(640×480) │                 │
│  │  USB   │  │ UART   │  │  CSI     │                 │
│  └───┬────┘  └───┬────┘  └────┬─────┘                 │
│      │           │             │                        │
│  ┌───▼───────────▼─────────────▼────────────────────┐  │
│  │           sae_sbc (C++ Qt)                       │  │
│  │                                                   │  │
│  │  ServeurTcp ◄── TCP:8884 ── commandes             │  │
│  │      │                                            │  │
│  │      ▼                                            │  │
│  │  Controleur (modeManuel / PID)                    │  │
│  │      │                                            │  │
│  │      ├──► I2C → Moteur DC (MD04)                  │  │
│  │      └──► PWM → ServoMoteur (direction)           │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  video_streamer.py (Python)                       │  │
│  │  Picamera2 → JPEG → TCP:8885 ──► streaming       │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                        │ WiFi / Tailscale VPN
                        ▼
┌──────────────── PC WINDOWS ─────────────────────────────┐
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  teleop_client.py (Python)                        │  │
│  │                                                    │  │
│  │  ┌──────── Thread VideoReceiver ─────────────┐    │  │
│  │  │ Réception/décodage JPEG (non-bloquant)     │    │  │
│  │  └──────────────────┬─────────────────────────┘    │  │
│  │                     │ frame                         │  │
│  │                     ▼                               │  │
│  │  ┌──────── Boucle principale (30 Hz) ────────┐    │  │
│  │  │ keyboard.is_pressed() → touches simultanées│    │  │
│  │  │ Rampe accélération + kick-start            │    │  │
│  │  │ Envoi TELEOP:DRIVE,speed,angle (20 Hz)     │    │  │
│  │  │ HUD + cv2.imshow                           │    │  │
│  │  └─────────────────────────────────────────────┘    │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## Communication réseau

### Ports et protocoles

| Port | Direction | Type | Contenu |
|------|-----------|------|---------|
| **8885** | Pi → PC | TCP binaire | Frames JPEG (préfixe 4 bytes) |
| **8884** | PC → Pi | TCP texte `\n` | Commandes TELEOP |

### Protocole vidéo (port 8885)

```
┌──────────────┬────────────────────────────────────┐
│ 4 bytes      │ N bytes                            │
│ uint32 BE    │ Données JPEG                       │
│ = taille N   │                                    │
└──────────────┴────────────────────────────────────┘
  ← répétition en boucle continue (~30 images/s) →
```

### Protocole commandes (port 8884)

**Commande principale (mode RC continu) :**

```
TELEOP:DRIVE,<vitesse>,<angle>\n
```

| Paramètre | Plage | Exemple | Signification |
|-----------|-------|---------|---------------|
| vitesse | [-1.0, 1.0] | 0.1800 | Positif = avant, négatif = arrière |
| angle | [-1.0, 1.0] | -0.3000 | Négatif = gauche, positif = droite |

**Commandes discrètes (rétrocompatibilité) :**

| Commande | Action |
|----------|--------|
| `TELEOP:STOP` | Arrêt total (vitesse = 0, angle = 0) |
| `TELEOP:FWD` | Avancer (vitesse = 0.15) |
| `TELEOP:BWD` | Reculer (vitesse = -0.10) |
| `TELEOP:LEFT` | angle -= 0.1 |
| `TELEOP:RIGHT` | angle += 0.1 |

---

## Téléopération RC

### Architecture multi-thread du client

```
teleop_client.py
│
├── Thread VideoReceiver (daemon)
│   • Socket TCP:8885 → réception JPEG continue
│   • Décodage OpenCV dans le thread
│   • Frame disponible via get_frame() (thread-safe)
│   • ⚡ Ne bloque JAMAIS la boucle principale
│
└── Thread principal (30 Hz)
    • keyboard.is_pressed() → détection simultanée
    • Calcul rampe accélération / décélération
    • Envoi TELEOP:DRIVE à 20 Hz max
    • Affichage HUD + cv2.imshow
```

### Contrôles (combinables simultanément !)

| Touche(s) | Action |
|-----------|--------|
| **Z** | Accélérer (rampe progressive + kick-start) |
| **S** | Reculer (rampe progressive) |
| **Q** | Tourner à gauche |
| **D** | Tourner à droite |
| **Z+Q** | Avancer ET tourner gauche |
| **Z+D** | Avancer ET tourner droite |
| **S+Q/D** | Reculer ET tourner |
| **Espace** | Arrêt d'urgence |
| **T** | Test servo (cycle d'angles) |
| **R** | Recentrer direction |
| **ESC** | Quitter |

### Chronogramme d'accélération

```
Vitesse
  0.18 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ max
       │                    ╱‾‾‾‾‾‾‾‾‾‾‾‾‾‾╲
       │                ╱                      ╲
       │             ╱ rampe +0.012/tick          ╲ ×0.90/tick
       │          ╱                                  ╲
  0.06 ┤───── ╱ kick-start                             ╲
       │   ╱                                              ╲
  0.00 ┤──╱────────────────────────────────────────────────╲──►
       t=0   Z enfoncé                Z relâché        arrêt
         │                               │
         └── accélération ──────────────┘└── décélération ──│
```

### Paramètres ajustables (teleop_client.py)

| Paramètre | Valeur | Description |
|-----------|--------|-------------|
| `MAX_FWD_SPEED` | 0.18 | Vitesse max avant |
| `MAX_BWD_SPEED` | -0.12 | Vitesse max arrière |
| `ACCEL_STEP` | 0.012 | Accélération par tick |
| `KICK_START` | 0.06 | Boost initial (franchit l'inertie) |
| `DECEL_FACTOR` | 0.90 | Multiplicateur décélération auto |
| `ANGLE_STEP` | 0.08 | Incrément direction par tick |
| `ANGLE_RETURN` | 0.04 | Rappel automatique au centre |

---

## Chaîne de commande matérielle

### Vitesse (I2C → Moteur DC MD04)

```
TELEOP:DRIVE,0.18,0.00
        │
        ▼
Controleur::handleManualCommand()
        │  manualSpeed = 0.18
        ▼
MaterielReel::deplacer(0.18, 0.00)
        │
        ▼
setI2CMotor(0.18)
        │  direction = 2 (avant), vitesse = 0.18 × 255 = 45
        ▼
I2C write /dev/i2c-1, addr 0x58
        │  Registre 0 = direction, Registre 2 = vitesse
        ▼
Moteur DC tourne
```

### Direction (PWM → Servo)

```
TELEOP:DRIVE,0.00,0.50
        │
        ▼
Controleur::handleManualCommand()
        │  manualAngle = 0.50
        ▼
MaterielReel::deplacer(0.00, 0.50)
        │
        ▼
direction.setPosition(0.50)
        │
        ▼
ServoMoteur::updatePos()
        │  gain = gainPosDuty_us = 300
        │  duty = (0.50 × 300 + 1500) × 1000 = 1,650,000 ns
        ▼
PWM::setDuty(1650000)
        │
        ▼
/sys/class/pwm/pwmchip0/pwm0/duty_cycle = 1650000
        │
        ▼
GPIO 18 (pin physique 12) → Signal PWM 50 Hz → Servo
```

| Angle | Duty (µs) | Position servo |
|-------|-----------|----------------|
| -1.0 | 1030 | Gauche max |
| 0.0 | 1500 | Centre |
| +1.0 | 1800 | Droite max |

---

## Mode autonome PID

> ⚠️ Temporairement désactivé (`modeManuel = true`)

Le mode autonome utilise :
- **LIDAR RPLidar** — Scan 360° → distances aux murs
- **PID** — Calcul d'erreur gauche/droite pour suivi de trajectoire
- **SpeedController** — Adaptation de vitesse selon angle de braquage
- **TFmini** — Distance frontale complémentaire

Pour réactiver : `modeManuel{false}` dans `controleur.h` ou commande TCP `AUTO:ON`.

Le code PID (`computeError`, `pid.update`, `speedCtrl.update`) est **100% intact**.

---

## Configuration matérielle

### /boot/firmware/config.txt

```ini
dtparam=i2c_arm=on
dtoverlay=pwm-2chan,pin=18,func=2,pin2=19,func2=2
```

### Broches utilisées

| Broche | GPIO | Fonction |
|--------|------|----------|
| Pin 12 | GPIO 18 | **PWM0** → Servo direction |
| Pin 3/5 | SDA1/SCL1 | **I2C** → Moteur MD04 (addr 0x58) |
| USB | — | LIDAR RPLidar (/dev/ttyUSB0) |
| UART | — | TFmini (/dev/ttyAMA1) |
| CSI | — | Picamera2 |

---

## Installation

### Raspberry Pi

```bash
# 1. Cloner le repo
git clone https://github.com/bounina/Voiture-Autonome-Qt.git
cd Voiture-Autonome-Qt

# 2. Compiler
mkdir -p build && cd build
qmake ../sae_sbc.pro
make -j4

# 3. Dépendances Python
pip3 install picamera2 opencv-python numpy
```

### PC Windows

```bash
# Dépendances Python
pip install opencv-python numpy keyboard
```

---

## Mode d'emploi

### Étape 1 — Raspberry Pi (2 terminaux SSH)

```bash
# Terminal 1 : C++ (moteurs + commandes)
cd ~/projets/Voiture-Autonome-Qt/build
sudo ./sae_sbc

# Terminal 2 : Streaming vidéo
cd ~/projets/Camera_arriere/src
python3 video_streamer.py --rotate 180
```

### Étape 2 — PC Windows

```bash
python teleop_client.py --pi-ip 100.114.87.93
```

> Remplacer par l'IP de votre Pi (`hostname -I`) ou l'IP Tailscale.

### Étape 3 — Piloter !

Cliquez sur la fenêtre vidéo, puis utilisez **Z/S/Q/D** (combinables).

```
         Z (avancer)
         ↑
   Q ← ─ ┼ ─ → D
         ↓
         S (reculer)

   ESPACE = arrêt d'urgence
   ESC = quitter
```

---

## Structure des dépôts

### 📁 [Voiture-Autonome-Qt](https://github.com/bounina/Voiture-Autonome-Qt)

```
Voiture-Autonome-Qt/
├── controleur.cpp/h        ← PID + mode manuel TELEOP
├── serveurtcp.cpp/h        ← Serveur TCP port 8884
├── mainwindow.cpp/h        ← Câblage signaux/slots Qt
├── materielreel.cpp/h      ← I2C moteur + servo direction
├── servomoteur.cpp/h       ← PWM servo (pwmchip0/pwm0)
├── pwm.cpp/h               ← Accès sysfs PWM
├── tfmini.cpp/h            ← Capteur distance frontal
├── sae_sbc.pro             ← Projet Qt
├── RESUME_ARCHITECTURE.txt ← Documentation technique détaillée
├── README.md               ← Ce fichier
└── python_camera/
    ├── teleop_client.py    ← [PC] Client téléop multi-thread
    ├── video_streamer.py   ← [PI] Serveur streaming JPEG
    └── test_servo_gpio.py  ← [PI] Diagnostic PWM servo
```

### 📁 [Camera_arriere](https://github.com/bounina/Camera_arriere)

```
Camera_arriere/
└── src/
    ├── video_streamer.py   ← [PI] Serveur streaming
    ├── teleop_client.py    ← [PC] Client téléopération
    └── phase3_calibrate    ← [PI] Calibration parking
```

---

## Problèmes résolus

| # | Problème | Solution |
|---|----------|----------|
| 1 | VNC à 1-2 FPS | JPEG-over-TCP → 30 FPS |
| 2 | Segfault quand LIDAR absent | Null-guard `drv` + timer stop |
| 3 | pwmchip2 inexistant | dtoverlay pwm-2chan → pwmchip0 |
| 4 | Servo muet sur GPIO 12 | Servo sur GPIO 18 → `pin=18,func=2` |
| 5 | Erreurs I2C MD04 au démarrage | Stabilisation progressive, pas bloquant |
| 6 | Stream gelé quand touche appuyée | VideoReceiver en **thread séparé** |
| 7 | Une seule touche à la fois | Bibliothèque **keyboard** → simultané |
| 8 | Démarrage lent | **Kick-start** 6% + rampe accélération |

---

## Workflow Git

```
PC Windows                              Raspberry Pi
   │                                         │
   │  git push C++ & Python                  │
   │──────────────────────► GitHub           │
   │                                         │
   │                           git pull ◄────│
   │                           qmake + make  │
   │                                         │
   │  python teleop_client.py                │
   │◄──── vidéo TCP:8885 ───────────────────│  video_streamer.py
   │───── cmds  TCP:8884 ──────────────────►│  sudo ./sae_sbc
```

---

## Licence

Projet académique SAE — IUT.
