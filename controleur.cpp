// controleur.cpp

#include "controleur.h"
#include <QDebug>
#include <QThread>
#include <cmath>

Controleur::Controleur(std::array<int,360>& _distances_mm)
    : distances_mm(_distances_mm)
{
    timer.start();
}

void Controleur::initPID(double _kp, double _ki, double _kd, double _k_anticipation)
{
    kp = _kp;
    ki = _ki;
    kd = _kd;
    k_anticipation = _k_anticipation;
    I = 0.0;
    erreur_prec = 0.0;
    firstRun = true;
    timer.restart();
}

void Controleur::newDatas()
{
    if (!isRunning) {
        emit deplacer(0,0);
        return;
    }

    // 1) Calcul de l'erreur et de l'anticipation
    double erreurd =0.0;
    double erreurg =0.0;
    double erreur = 0.0;
    double anticipation = 0.0;
    for (int i = 0; i <= 105; ++i) {
        double rad = i * M_PI / 180.0;
       erreurd += std::sin(rad) * distances_mm.at(i + 180);
       erreurg += std::sin(rad) * distances_mm.at(180 - i);
       erreur = erreurd - erreurg;
    }
    for (int i = 30; i <= 85; i += 5) {
        double rad = i * M_PI / 180.0;
        anticipation += distances_mm.at(180 + i) * std::sin(rad);
    }
    for (int i = -85; i <= -30; i += 5) {
        double rad = i * M_PI / 180.0;
        anticipation -= distances_mm.at(180 + i) * std::sin(rad);
    }

    // 2) Mesure du dt
    double dt = 0.0;
    if (!firstRun) {
        dt = timer.elapsed() / 1000.0;  // en secondes
    } else {
        firstRun = false;
    }
    timer.restart();

    // 3) Terme intégral
    I += erreur * dt;

    // 4) Terme dérivé
    double D = dt > 0 ? (erreur - erreur_prec) / dt : 0.0;
    erreur_prec = erreur;

    // 5) Décalage de virage (comme avant)
    double decalage_virage = 0.0;
    if (std::abs(anticipation) > 500000000) {
        decalage_virage = -anticipation / 15.0;
    }

    // 6) Calcul PID + anticipation
    double angle = kp*(erreur+ decalage_virage)
                   + ki*I
                   + kd*D
                   + k_anticipation*anticipation;

    // 7) Saturation [-1 ; 1]
    angle = std::clamp(angle, -1.0, 1.0);

    // 8) Envoi commande
    double vitesse = 0.35;  // reste constante
    emit deplacer(vitesse, angle);

    // 9) Debug
    QString debug = QString("v=%1 | err=%2 | I=%3 | D=%4 | ant=%5 | dec=%6 | ang=%7")
                        .arg(vitesse)
                        .arg(erreur)
                        .arg(I)
                        .arg(D)
                        .arg(anticipation)
                        .arg(decalage_virage)
                        .arg(angle);
    emit sendAffichage(debug);
    qDebug() << debug;
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
    double vitesse = 0.0; // vitesse constante pour les tests
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

