#include "controleur.h"
#include <QDebug>
#include <QThread>

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
    qDebug() << message;
    if (message == "on") isRunning = true;
    else if (message == "off") isRunning = false;
    else if (message == "test_angle") testBoucleDirection();
    else if (message == "test_vitesse") testBoucleVitesse();

    qDebug() << isRunning;
}


void Controleur::testBoucleDirection()
{
    double vitesse = 0.4; // vitesse constante pour les tests
    double step = 0.1; // pas d'incrémentation de l'angle
    double angle = -1.0;

    // Balayage de -1 à 1
    while (angle <= 1.0)
    {
        emit deplacer(vitesse, angle);
        QString info = "Test -> Vitesse : " + QString::number(vitesse) + " | Angle : " + QString::number(angle);
        emit sendAffichage(info);
        qDebug() << info;

        angle += step;
        QThread::msleep(300); // Petite pause pour voir l'effet
    }

    // Balayage retour de 1 à -1
    angle = 1.0 - step;
    while (angle >= -1.0)
    {
        emit deplacer(vitesse, angle);
        QString info = "Test <- Vitesse : " + QString::number(vitesse) + " | Angle : " + QString::number(angle);
        emit sendAffichage(info);
        qDebug() << info;

        angle -= step;
        QThread::msleep(300);
    }

    emit deplacer(0, 0); // Arrêt à la fin du test
}


void Controleur::testBoucleVitesse()
{
    double angle = 0.0; // direction fixe
    double step = 0.05; // pas d'augmentation de la vitesse
    double vitesse = 0.0;

    // Balayage de 0 à 0.65
    while (vitesse <= 0.8)
    {
        emit deplacer(vitesse, angle);
        QString info = "Test -> Vitesse : " + QString::number(vitesse) + " | Angle : " + QString::number(angle);
        emit sendAffichage(info);
        qDebug() << info;

        vitesse += step;
        QThread::msleep(300);
    }

    // Balayage retour de 0.65 à 0
    vitesse = 0.8 - step;
    while (vitesse >= 0.0)
    {
        emit deplacer(vitesse, angle);
        QString info = "Test <- Vitesse : " + QString::number(vitesse) + " | Angle : " + QString::number(angle);
        emit sendAffichage(info);
        qDebug() << info;

        vitesse -= step;
        QThread::msleep(300);
    }

    emit deplacer(0, 0); // Arrêt à la fin
}


