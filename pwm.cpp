#include "pwm.h"
#include <QDebug>
#include <QDir>
#include <QThread>

PWM::PWM(const int pwmChip, const int pwmChannel, int Fmli)
    :period(1000000000/Fmli)
{


    QDir baseDir("/sys/class/pwm/pwmchip"+QString::number(pwmChip));
    if (!baseDir.exists())
    {
        qDebug()<<"erreur, pas de pwm : "<<baseDir.absolutePath();
        exit(EXIT_FAILURE);
    }

    QFile exportFile(baseDir.filePath("export"));
    if (!exportFile.open(QIODevice::WriteOnly))
    {
        qDebug()<<"Cannot create the file "+ exportFile.fileName();
        exit(EXIT_FAILURE);
    }
    else
    {
        QTextStream out(&exportFile);
        out<<QString::number(pwmChannel);
        exportFile.close();
    }

    QDir pwmDir(baseDir.absolutePath()+"/pwm"+QString::number(pwmChannel));
    int nb=0;
    while(pwmDir.exists()==false)
    {
        QThread::msleep(10);
        nb++;
        if (nb>60)
        {
            qDebug()<<"erreur, création de la pwm : "<<pwmDir.absolutePath();
            exit(EXIT_FAILURE);
        }
    }

    QFile periodFile(pwmDir.filePath("period"));
    if (!periodFile.open(QIODevice::WriteOnly))
    {
        qDebug()<<"Cannot create the file "+ periodFile.fileName();
        exit(EXIT_FAILURE);
    }
    else
    {
        QTextStream out(&periodFile);
        out<<QString::number(period);
        periodFile.close();
    }

    rapportCycliqueFile.setFileName(pwmDir.filePath("duty_cycle"));
    if (!rapportCycliqueFile.open(QIODevice::WriteOnly))
    {
        qDebug()<<"Cannot create the file "+ rapportCycliqueFile.fileName();
        exit(EXIT_FAILURE);
    }
    else
    {
        outRapportCylicque.setDevice(&rapportCycliqueFile);
        outRapportCylicque<<QString::number(0);
        outRapportCylicque.flush();
    }

    QFile enableFile(pwmDir.filePath("enable"));
    if (!enableFile.open(QIODevice::WriteOnly))
    {
        qDebug()<<"Cannot create the file "+ enableFile.fileName();
        exit(EXIT_FAILURE);
    }
    else
    {
        QTextStream out(&enableFile);
        out<<QString::number(1);
        enableFile.close();
    }

    qDebug() << "[PWM] Init OK:" << pwmDir.absolutePath()
             << "period=" << period << "ns (" << Fmli << "Hz)";
}

void PWM::setDuty(int duty)
{
    if (duty<=period)
    {
        outRapportCylicque<<QString::number(duty);
        outRapportCylicque.flush();
        // Debug: log toutes les 50 écritures
        static int pwmLogCounter = 0;
        if (++pwmLogCounter % 50 == 0) {
            qDebug() << "[PWM] duty_cycle =" << duty << "ns"
                     << "(" << (duty / 1000) << "us)"
                     << "file:" << rapportCycliqueFile.fileName();
        }
    }
    else
    {
        qDebug()<<"erreur duty cycle ! duty=" << duty << " > period=" << period;
    }
}
