// MaterielReel.cpp

#include "materielreel.h"
#include <QtMath>


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


MaterielReel::MaterielReel()
{

    // Timer LIDAR
    tictocLidar.setInterval(50);
    tictocLidar.start();
    connect(&tictocLidar, &QTimer::timeout,
            this, &MaterielReel::lidarValue);

    // Initialisation du driver LIDAR
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
            } else {
                delete drv;
                drv = nullptr;
                qDebug() << "Impossible de récupérer les infos du LIDAR";
            }
            drv->setMotorSpeed();
            drv->startScan(0, 1);
        } else {
            qDebug() << "Échec de connexion au LIDAR";
        }
    }

    // Initialisation du capteur TFmini
    tfmini = new TFmini();
    if (!tfmini->init()) {
        qDebug() << "Erreur d'initialisation du TFmini";
    } else {
        qDebug() << "TFmini initialisé avec succès";
    }

    // Timer TFmini
    tictocTFmini.setInterval(100);
    tictocTFmini.start();
    connect(&tictocTFmini, &QTimer::timeout,
            this, &MaterielReel::tfminiValue);
}

void MaterielReel::lidarValue()
{
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





void MaterielReel::deplacer(double _vitesse, double _angle)
{
    vitesse.setPosition(_vitesse);
    direction.setPosition(_angle);
}
