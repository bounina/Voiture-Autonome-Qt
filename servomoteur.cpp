#include "servomoteur.h"

ServoMoteur::ServoMoteur(const int pwmChannel,
                         const int _centerDuty_us,
                         const int _gainPosDuty_us,
                         const int _gainNegDuty_us)
    : pwm(0, pwmChannel, 50),   // pwmchip0 (vérifié: ls /sys/class/pwm/)
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
    qDebug() << "[SERVO] pos=" << pos << "-> duty=" << static_cast<int>(duty)
             << "ns (" << static_cast<int>(duty/1000) << "us)"
             << "center=" << centerDuty_us << "gain=" << gain;
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
