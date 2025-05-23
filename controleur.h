#ifndef CONTROLEUR_H
#define CONTROLEUR_H

#include <QtMath>
#include <QObject>
#include <array>
#include <QElapsedTimer>

using std::array;

class Controleur : public QObject
{
    Q_OBJECT

public:
    explicit Controleur(std::array<int,360>& distances_mm);

    void initPID(double _kp, double _ki, double _kd, double _k_anticipation);
    void newDatas();
    void conversion();
    void onoff(QString message);

signals:
    void deplacer(double vitesse, double angle);
    void sendAffichage(const QString&);
    void donneeconvertion(const QString&);

private:
    void testBoucleDirection();
    void testBoucleVitesse();

    std::array<int,360>& distances_mm;
    bool isRunning = false;

    // PID
    double kp = 0.0;
    double ki = 0.0;
    double kd = 0.0;
    double k_anticipation = 0.0;

    double I = 0.0;             // Terme intégral
    double erreur_prec = 0.0;   // Dernière erreur
    QElapsedTimer timer;        // Pour mesurer dt
    bool firstRun = true;
};

#endif // CONTROLEUR_H
