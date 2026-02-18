// MaterielReel.h
#ifndef MATERIELREEL_H
#define MATERIELREEL_H

#include <QObject>
#include <QTimer>
#include <QDebug>
#include "pwm.h"
#include "servomoteur.h"
#include "materiel.h"
#include "tfmini.h"
#include "sl_lidar_driver.h"

// Inclusions nécessaires pour la communication I2C sous Linux
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/i2c-dev.h>

using namespace std;
using namespace sl;

extern ILidarDriver* drv;

class MaterielReel : public Materiel
{
    Q_OBJECT

public:
    MaterielReel();
    ~MaterielReel(); // Destructeur pour fermer proprement le bus I2C et arrêter le moteur

public slots:
    void tfminiValue();
    void lidarValue();
    void deplacer(double _vitesse, double _angle);

signals:
    void newDatas();
    void tfminiDistanceChanged(int distance_cm);

private:
    // --- METHODES INTERNES I2C ---
    bool initI2CMotor();
    void setI2CMotor(double _vitesse);

    // --- VARIABLES I2C (Driver MD04) ---
    int i2c_fd{-1};                   // Descripteur de fichier pour le bus I2C
    const int I2C_ADDR = 0x58;        // Adresse I2C du MD04
    const char* I2C_BUS = "/dev/i2c-1"; // Bus I2C standard du Raspberry Pi

    // NOUVEAU : Mémoire cache pour éviter de spammer le bus I2C (Anti-emballement)
    unsigned char last_speed_val = 255;   // Valeur initiale invalide
    unsigned char last_command_val = 255; // Valeur initiale invalide
    // -----------------------------------

    QTimer tictocLidar;

    // Seul le servo de direction est conservé (la vitesse est gérée par le MD04)
    ServoMoteur direction{2,1500,300,470}; // droite/gauche

    TFmini *tfmini;              // Capteur TFmini
    QTimer tictocTFmini;
    int tfminiDistance{0};
};

#endif // MATERIELREEL_H
