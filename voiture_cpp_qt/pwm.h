#ifndef PWM_H
#define PWM_H

#include <QObject>
#include <QFile>
#include <QTextStream>

class PWM : public QObject
{
    Q_OBJECT
public:
    explicit PWM(const int pwmChip,const int pwmChannel,int Fmli);
private:
    QFile rapportCycliqueFile;
    QTextStream outRapportCylicque;
    const int period;

public slots:
    void setDuty(int duty);

signals:
};

#endif // PWM_H
