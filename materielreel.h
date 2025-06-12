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

using namespace std;
using namespace sl;

extern ILidarDriver* drv;

class MaterielReel : public Materiel
{
    Q_OBJECT

public:
    MaterielReel();

public slots:
    void tfminiValue();
    void lidarValue();
    void deplacer(double _vitesse, double _angle);

signals:
    void newDatas();
    void tfminiDistanceChanged(int distance_cm);

private:
    QTimer tictocLidar;
    ServoMoteur vitesse{2,1500,300,300};
    ServoMoteur direction{3,1500,300,300};
    TFmini *tfmini;              // Capteur TFmini
    QTimer tictocTFmini;
    int tfminiDistance{0};
};

#endif // MATERIELREEL_H
