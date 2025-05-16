#ifndef CONTROLEUR_H
#define CONTROLEUR_H

#include <QtMath>
#include <QObject>
#include <array>

using std::array;

class Controleur : public QObject
{
    Q_OBJECT

public:
    Controleur(array<int,360>&_distances_mm);
    // coefficients:
    bool isRunning=false;
    double kpv;
    double kp;
    double ki;
    double kd;
    void initPID(double _kp, /*double _ki, double _kd,*/ double _kpv);
    // erreurs:
    double erreur_precedente;
    double somme_erreurs;
    array<int,360>&distances_mm;


signals:
    void deplacer(double vitesse, double angle);
    void donneeconvertion(QString );
    void sendAffichage(QString);
public slots:
    void newDatas();
    void conversion();
    void onoff(QString);
    void testBoucleDirection();
    void testBoucleVitesse();


private:

};

#endif
