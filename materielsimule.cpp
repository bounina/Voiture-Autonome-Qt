#include "materielsimule.h"
#include <QDebug>
MaterielSimule::MaterielSimule()
{
    connect(&tcp, &ClientTCP::newDatas,
            this, &MaterielSimule::processTcpDatas);
}

void MaterielSimule::processTcpDatas(QString data)
{
    QStringList array = data.split(';');

    for(int i=0; i<= 359; i++)
    {
        distances_mm.at(i) = array.at(i).toInt();
    }
    emit newDatas();
}

void MaterielSimule::deplacer(double _vitesse, double _angle)
{
    QString vitesse = vitesse.number(_vitesse, 'f', 4);
    QString angle = QString::number(_angle, 'f', 4);
    QString resultat = vitesse + ";" + angle;
    tcp.sendDatas(resultat);
    QString envoi = "la vitesse est de " + vitesse + "\n" + "l'angle est de " + angle;
    emit sendAffichage(envoi);
}
