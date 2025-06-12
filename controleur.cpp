// Controleur.cpp
#include "controleur.h"
#include <QDebug>
#include <QThread>

Controleur::Controleur(std::array<int,360>& distancesMm, QObject* parent)
    : QObject(parent)
    , distances_mm(distancesMm)
{
    timer.start();
    speedCtrl.currentSpeed = vmin;
}

void Controleur::initPID(double _kp, double _ki, double _kd)
{
    pid.kp       = _kp;
    pid.ki       = _ki;
    pid.kd       = _kd;
    pid.I        = 0.0;
    pid.prevErr  = 0.0;
    pid.firstRun = true;
    timer.restart();
}

void Controleur::onTfminiDistance(int dist_cm)
{
    // Mise à jour de la distance TFmini
    tfminiDistCm = dist_cm;
}

void Controleur::newDatas()
{
    if (!isRunning) {
        emit deplacer(0.0, 0.0);
        return;
    }

    // 1) Si obstacle devant → mode reverse
    if (handleReverseDetection()) {
        handleReverseMovement();
        return;
    }
    if (revPhase != ReversePhase::Idle) {
        handleReverseMovement();
        return;
    }

    // 2) Boucle PID normale
    double error = computeError();
    double dt    = timer.restart() / 1000.0;
    double angle = pid.update(error, dt);
    double speed = speedCtrl.update(angle);

    emit deplacer(speed, angle);
    sendDebugInfo(speed, error);
}

bool Controleur::handleReverseDetection()
{
    if (revPhase != ReversePhase::Idle) return false;

    double distFront = (distances_mm[179] + distances_mm[180] + distances_mm[181]) / 3.0;
    if (distFront >= seuilReverse) return false;

    // ** Nouveau : si TFmini détecte < 15 cm en marche arrière, on stoppe **
    if (tfminiDistCm <= 15) {
        qDebug() << "[REVERSE] TFmini obstacle à" << tfminiDistCm << "cm → arrêt";
        revPhase = ReversePhase::Idle;
        emit deplacer(0.0, 0.0);
        return true;
    }

    double sumL = sumRange(distances_mm,  60, 120);
    double sumR = sumRange(distances_mm, 240, 300);
    reverseTimer.restart();

    if (sumL < seuilSideClear && sumR < seuilSideClear) {
        revPhase = ReversePhase::Straight;
        qDebug() << "[REVERSE] both sides blocked";
    } else {
        revPhase = ReversePhase::Turn1;
        turnLeftFirst = (sumL > sumR);
        qDebug() << "[REVERSE] turnLeftFirst =" << turnLeftFirst;
    }
    return true;
}

void Controleur::handleReverseMovement()
{
    // ** Nouveau : si TFmini detecte obstacle pendant reversal, on stoppe et repart normal **
    if (tfminiDistCm <= 15) {
            revPhase = ReversePhase::Idle;
        return;
    }

    if (revPhase == ReversePhase::Straight) {
        double sumL = sumRange(distances_mm,  60, 120);
        double sumR = sumRange(distances_mm, 240, 300);
        if (sumL >= seuilSideClear || sumR >= seuilSideClear) {
            revPhase = ReversePhase::Turn1;
            turnLeftFirst = (sumL > sumR);
            reverseTimer.restart();
        } else {
            emit deplacer(vitesseReverse, 0.0);
            return;
        }
    }

    int t = static_cast<int>(reverseTimer.elapsed());
    if (t < phase1Ms) {
        double ang = turnLeftFirst ? +angleS : -angleS;
        emit deplacer(vitesseReverse, ang);
    }
    else if (t < phase1Ms + phase2Ms) {
        revPhase = ReversePhase::Turn2;
        double ang = turnLeftFirst ? -angleS : +angleS;
        emit deplacer(vitesseReverse, ang);
    }
    else {
        revPhase = ReversePhase::Idle;
        emit deplacer(0.0, 0.0);
    }
}

double Controleur::computeError() const
{
    double errR = 0.0, errL = 0.0;
    for (int i = 0; i <= 100; ++i) {
        double rad = M_PI * i / 180.0;
        errR += std::sin(rad) * distances_mm[180 + i];
        errL += std::sin(rad) * distances_mm[180 - i];
    }
    return errR - errL;
}

void Controleur::sendDebugInfo(double vTarget, double error)
{
    QString debug = QString("vCible=%1 | err=%2 | P=%3 | I=%4 | D=%5")
                        .arg(vTarget,   0, 'f', 2)
                        .arg(error,     0, 'f', 2)
                        .arg(pid.lastP, 0, 'f', 2)
                        .arg(pid.lastI, 0, 'f', 2)
                        .arg(pid.lastD, 0, 'f', 2);

    emit sendAffichage(debug);
    qDebug() << debug;
}

double Controleur::sumRange(
    const std::array<int,360>& D,
    int start, int end, int step
    ) {
    double sum = 0.0;
    for (int d = start; d <= end; d += step)
        sum += D[d];
    return sum;
}

void Controleur::conversion()
{
    QString msg;
    for (int i = 0; i < 360; ++i) {
        msg += QString::number(distances_mm[i]);
        if (i != 359) msg += ';';
    }
    emit donneeconvertion(msg);
}

void Controleur::onoff(const QString& message)
{
    qDebug() << message;
    if      (message == "on")         isRunning = true;
    else if (message == "off")        isRunning = false;
    else if (message == "test_angle") testBoucleDirection();
    else if (message == "test_vitesse") testBoucleVitesse();
    qDebug() << "isRunning =" << isRunning;
}

void Controleur::testBoucleDirection()
{
    double vitesse = 0.0, step = 0.1, angle = -1.0;
    while (angle <= 1.0) {
        emit deplacer(vitesse, angle);
        QString info = QString("Test -> V:%1 | A:%2").arg(vitesse).arg(angle);
        emit sendAffichage(info);
        qDebug() << info;
        angle += step;
        QThread::msleep(300);
    }
    angle = 1.0 - step;
    while (angle >= -1.0) {
        emit deplacer(vitesse, angle);
        QString info = QString("Test <- V:%1 | A:%2").arg(vitesse).arg(angle);
        emit sendAffichage(info);
        qDebug() << info;
        angle -= step;
        QThread::msleep(300);
    }
    emit deplacer(0.0, 0.0);
}

void Controleur::testBoucleVitesse()
{
    double angle = 0.0, step = 0.05, vitesse = 0.0;
    while (vitesse <= 0.8) {
        emit deplacer(vitesse, angle);
        QString info = QString("Test -> V:%1 | A:%2").arg(vitesse).arg(angle);
        emit sendAffichage(info);
        qDebug() << info;
        vitesse += step;
        QThread::msleep(300);
    }
    vitesse = 0.8 - step;
    while (vitesse >= 0.0) {
        emit deplacer(vitesse, angle);
        QString info = QString("Test <- V:%1 | A:%2").arg(vitesse).arg(angle);
        emit sendAffichage(info);
        qDebug() << info;
        vitesse -= step;
        QThread::msleep(300);
    }
    emit deplacer(0.0, 0.0);
}
