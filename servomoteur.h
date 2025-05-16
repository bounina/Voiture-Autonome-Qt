 #ifndef SERVOMOTEUR_H
#define SERVOMOTEUR_H

#include <QObject>
#include "pwm.h"

class ServoMoteur : public QObject
{
    Q_OBJECT
public:
    explicit ServoMoteur(const int pwmChannel,const int _centerDuty_us,const int _gainDuty_us);
private:
    PWM pwm;
    double pos;
    double centerDuty_us;
    double gainDuty_us;

    void updatePos();
public slots:
    void setPosition(double newPos);
signals:
};

#endif // SERVOMOTEUR_H
