#ifndef MATERIELREEL_H
#define MATERIELREEL_H

#include "pwm.h"
#include "servomoteur.h"
#include "materiel.h"
#include <QObject>
#include <QDebug>
#include <QTimer>
#include "tfmini.h"
#include "sl_lidar_driver.h"
using namespace std;
using namespace sl;

extern ILidarDriver* drv;

class MaterielReel : public Materiel
{
public:
    MaterielReel();
public slots:
    void lidarValue();
    void deplacer(double _vitesse, double _angle);
signals:
private:
    QTimer tictocLidar;
    ServoMoteur vitesse{2,1500,300,300};
    ServoMoteur direction{3,1500,300,300};
};

#endif // MATERIELREEL_H
