#include "controleur.h"
#include <QDebug>

Controleur::Controleur(array<int,360>&_distances_mm) : distances_mm(_distances_mm)
{
}

void Controleur::newDatas()
{

 if (isRunning == true)
 {
    double angle = 0;
    double vitesse = 0;
    double erreur = 0;
    double erreurv = 0;
    double v1;
    double v2;
    for(int i=-10; i<11; i++)
    {
        double radians = (i*M_PI)/180;
        erreurv += cos(radians) * distances_mm.at(i+180);
    }
    vitesse = 0.000009571 * erreurv + 0.40;
    if(vitesse <0) vitesse = 0;
    if(vitesse >0.65) vitesse = 0.65;


     for(int i=-90; i<91; i++)
    {
       double radians = (i*M_PI)/180;
       erreur += sin(radians) * distances_mm.at(i+180);
    }
    angle = kp * erreur /*+ ki * somme_erreurs + kd * erreur_precedente*/ ;
    if(angle <-1) angle= -1; //droite
    if(angle >1) angle = 1; // gauche


    emit deplacer(vitesse, angle);
//    somme_erreurs += erreur;
//    erreur_precedente = erreur;

    QString envoi =  "la vitesse est "+QString::number(vitesse) +'\n'+"l'angle est "+ QString::number(angle);
    emit sendAffichage(envoi);
    qDebug()<<"l'envoi est"<<envoi;
  }
 else
 {
    emit deplacer(0,0);
 }

}




void Controleur::initPID(double _kp, /*double _ki, double _kd,*/double _kpv)
{
    kp = _kp;
//    ki = _ki;
//    kd = _kd;
    kpv = _kpv;
}

void Controleur::conversion()
{
    QString message;
    for(int i=0;i<360;i++)
    {
        message.append(QString::number(distances_mm.at(i)));
        if(i !=359)message.append(";");
    }
    emit donneeconvertion(message);
}

void Controleur::onoff(QString message)
{
    qDebug()<<message;
    if (message == "on")isRunning=true;
    else if (message == "off")isRunning=false;
    qDebug()<<isRunning;
}

