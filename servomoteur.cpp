#include "servomoteur.h"

ServoMoteur::ServoMoteur(const int pwmChannel,
                         const int _centerDuty_us,
                         const int _gainPosDuty_us,
                         const int _gainNegDuty_us)
    : pwm(2, pwmChannel, 50),
    centerDuty_us(_centerDuty_us),
    gainPosDuty_us(_gainPosDuty_us),
    gainNegDuty_us(_gainNegDuty_us)
{
    pos = 0;
    updatePos();
}

void ServoMoteur::updatePos()
{
    double gain = (pos >= 0) ? gainPosDuty_us : gainNegDuty_us;
    float duty = (pos * gain + centerDuty_us) * 1000;
    pwm.setDuty(static_cast<int>(duty));
}

void ServoMoteur::setPosition(double newPos)
{
    if (newPos != pos)
    {
        pos = newPos;
        if (pos > 1) pos = 1;
        if (pos < -1) pos = -1;
        updatePos();
    }
}
