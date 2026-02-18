// MaterielReel.cpp

#include "materielreel.h"
#include <QtMath>
#include <algorithm> // Pour std::clamp

#include <fcntl.h>         // O_RDWR
#include <unistd.h>        // open(), read(), close()
#include <sys/ioctl.h>     // ioctl()
#include <linux/i2c-dev.h> // I2C_SLAVE
#include <cerrno>          // errno
#include <cstring>         // strerror()

ILidarDriver* drv = nullptr;

#ifndef _countof
#define _countof(_Array) (int)(sizeof(_Array) / sizeof(_Array[0]))
#endif

// =====================================================================
// CONSTRUCTEUR / DESTRUCTEUR
// =====================================================================

MaterielReel::MaterielReel()
{
    // 1. Initialisation I2C Moteur MD04
    if (!initI2CMotor()) {
        qDebug() << "Erreur critique : Impossible d'initialiser le moteur I2C MD04";
    }

    // 2. Timer LIDAR
    tictocLidar.setInterval(50);
    tictocLidar.start();
    connect(&tictocLidar, &QTimer::timeout,
            this, &MaterielReel::lidarValue);

    // 3. Initialisation du driver LIDAR
    drv = *createLidarDriver();
    if (!drv) {
        qDebug() << "Erreur d'initialisation du driver LIDAR";
    } else {
        qDebug() << "Driver LIDAR OK";
        IChannel* channel = (*createSerialPortChannel("/dev/ttyUSB0", 115200));
        if (SL_IS_OK(drv->connect(channel))) {
            sl_lidar_response_device_info_t devinfo;
            if (SL_IS_OK(drv->getDeviceInfo(devinfo))) {
                qDebug() << "Connecté sur le LIDAR";
                    qDebug() << "SN:" << devinfo.serialnum;
                qDebug() << "Firmware:" << (devinfo.firmware_version >> 8) << "." << (devinfo.firmware_version & 0xFF)
                         << " HW rev:" << (int)devinfo.hardware_version;
                drv->setMotorSpeed();
                drv->startScan(0, 1);
            } else {
                delete drv;
                drv = nullptr;
                qDebug() << "Impossible de récupérer les infos du LIDAR";
                tictocLidar.stop(); // Pas de LIDAR -> on arrête le timer
            }
        } else {
            qDebug() << "Échec de connexion au LIDAR";
        }
    }

    // 4. Initialisation du capteur TFmini
    tfmini = new TFmini();
    if (!tfmini->init()) {
        qDebug() << "Erreur d'initialisation du TFmini";
    } else {
        qDebug() << "TFmini initialisé avec succès";
    }

    // 5. Timer TFmini
    tictocTFmini.setInterval(100);
    tictocTFmini.start();
    connect(&tictocTFmini, &QTimer::timeout,
            this, &MaterielReel::tfminiValue);
}

MaterielReel::~MaterielReel()
{
    // Fermeture propre pour éviter que le robot ne continue d'avancer
    if (i2c_fd >= 0) {
        // Envoi d'une commande d'arrêt forcée
        unsigned char buffer_stop_speed[2] = {0x02, 0};
        unsigned char buffer_stop_cmd[2]   = {0x00, 1}; // 1 ou 2, peu importe si speed est 0
        write(i2c_fd, buffer_stop_speed, 2);
        write(i2c_fd, buffer_stop_cmd, 2);

        close(i2c_fd);    // Fermeture du bus I2C
    }
}

// =====================================================================
// GESTION DU MOTEUR I2C (MD04) CORRIGÉE (INVERSION AVANT/ARRIÈRE)
// =====================================================================

bool MaterielReel::initI2CMotor()
{
    // Ouverture du bus I2C
    i2c_fd = open(I2C_BUS, O_RDWR);
    if (i2c_fd < 0) {
        qDebug() << "Erreur d'ouverture du bus I2C :" << strerror(errno);
        return false;
    }

    // Connexion à l'adresse 0x58 (MD04)
    if (ioctl(i2c_fd, I2C_SLAVE, I2C_ADDR) < 0) {
        qDebug() << "Erreur de connexion au MD04 (0x58) :" << strerror(errno);
        close(i2c_fd);
        i2c_fd = -1;
        return false;
    }

    // Configuration de l'accélération interne du MD04 (Registre 3)
    unsigned char buffer_accel[2] = {0x03, 5};
    if (write(i2c_fd, buffer_accel, 2) != 2) {
        qDebug() << "Erreur d'écriture de l'accélération MD04";
    }

    qDebug() << "Driver moteur MD04 initialisé avec succès.";
    return true;
}

void MaterielReel::setI2CMotor(double _vitesse)
{
    if (i2c_fd < 0) return;

    // 1. Limiter la consigne entre -1.0 et 1.0
    _vitesse = std::clamp(_vitesse, -1.0, 1.0);

    // 2. Calcul de la vitesse absolue (0 à 255)
    unsigned char speed_val = static_cast<unsigned char>(std::abs(_vitesse) * 255.0);

    // 3. Détermination de la commande (Registre 0) INVERSÉE
    // Maintenant : 2 = Marche avant, 1 = Marche arrière
    unsigned char command_val = 0;

    // Zone morte de 5% pour éviter les vibrations à l'arrêt
    if (_vitesse > 0.05) {
        command_val = 2; // <--- MODIFICATION ICI : 2 = Avance
    } else if (_vitesse < -0.05) {
        command_val = 1; // <--- MODIFICATION ICI : 1 = Recule
    } else {
        command_val = 2; // Arrêt (avec vitesse 0)
        speed_val = 0;
    }

    // 4. ANTI-SPAM I2C : On envoie seulement si la consigne a changé
    if (speed_val == last_speed_val && command_val == last_command_val) {
        return; // Rien à faire, le MD04 maintient déjà cette vitesse
    }

    // Adresses des registres du MD04
    const unsigned char REG_COMMAND = 0x00;
    const unsigned char REG_SPEED   = 0x02;

    // Préparation des buffers [Registre, Valeur]
    unsigned char buffer_speed[2]   = {REG_SPEED, speed_val};
    unsigned char buffer_command[2] = {REG_COMMAND, command_val};

    // Écriture sur le bus I2C
    if (write(i2c_fd, buffer_speed, 2) != 2 || write(i2c_fd, buffer_command, 2) != 2) {
        qDebug() << "Erreur d'écriture I2C sur le MD04 :" << strerror(errno);
    } else {
        // Mise en cache des dernières valeurs envoyées avec succès
        last_speed_val = speed_val;
        last_command_val = command_val;
        qDebug() << "Moteur MD04 -> Dir:" << command_val << "| Vitesse:" << speed_val;
    }
}

void MaterielReel::deplacer(double _vitesse, double _angle)
{
    // Envoi de la vitesse via I2C (sécurisé)
    setI2CMotor(_vitesse);
    // Envoi de l'angle via PWM (ServoMoteur existant)
    direction.setPosition(_angle);
}

// =====================================================================
// GESTION DES CAPTEURS (INCHANGÉE)
// =====================================================================

void MaterielReel::lidarValue()
{
    if (!drv) return;  // Pas de LIDAR connecté -> on ne fait rien

    sl_lidar_response_measurement_node_hq_t nodes[8192];
    size_t count = _countof(nodes);
    sl_result op_result = drv->grabScanDataHq(nodes, count);

    if (SL_IS_OK(op_result)) {
        distances_mm.fill(0);
        for (int i = 0; i < int(count); ++i) {
            int angle = qRound((nodes[i].angle_z_q14 * 90.0f) / 16384.0f);
            if (angle >= 180) angle -= 360;
            if (angle >= -180 && angle < 180) {
                int d = nodes[i].dist_mm_q2 / 4.0;
                if (d > 0) distances_mm.at(angle + 180) = d;
            }
        }
        // comble les trous
        for (int i = 0; i < 360; ++i) {
            if (distances_mm.at(i) == 0) {
                for (int j = 1; j < 10; ++j) {
                    int pos = (i + j) % 360;
                    if (distances_mm.at(pos) != 0) {
                        distances_mm[i] = distances_mm[pos];
                        break;
                    }
                }
            }
        }
        emit newDatas();
    } else {
        qDebug() << "Erreur de lecture LIDAR";
    }
}

void MaterielReel::tfminiValue()
{
    // 1) Lecture en cm
    int dist_cm = tfmini->getDistance();
    if (dist_cm <= 0) {
        return;
    }

    emit tfminiDistanceChanged(dist_cm);

    // 3) Filtre médian (tampon de 5 mesures)
    static QList<int> buffer;
    buffer.append(dist_cm);
    if (buffer.size() > 5)
        buffer.removeFirst();

    QList<int> sorted = buffer;
    std::sort(sorted.begin(), sorted.end());
    int med_cm = sorted.at(sorted.size() / 2);

    // 5) Stockage interne
    tfminiDistance = med_cm;
}
