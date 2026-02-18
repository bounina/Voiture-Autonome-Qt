// controleur.cpp
#include "controleur.h"
#include <QDebug>
#include <QThread>
#include <limits>

Controleur::Controleur(std::array<int,360>& distancesMm, QObject* parent)
    : QObject(parent)
    , distances_mm(distancesMm)
{
    timer.start();
    speedCtrl.currentSpeed = vmin;

    // configuration du timer de stabilité frontale
    frontStableTimer.setSingleShot(true);
    connect(&frontStableTimer, &QTimer::timeout,
            this, &Controleur::onFrontStableTimeout);
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
    tfminiDistCm = dist_cm;
}

void Controleur::newDatas()
{
    if (!isRunning) {
        emit deplacer(0, 0);
        return;
    }

    // détection de front immobile
//    handleReverseDetection();
//    if (revPhase != ReversePhase::Idle) {
//        handleReverseMovement();
//        return;
//    }

    // conduite normale
    double error = computeError();
    double dt    = timer.restart() / 1000.0;
    double angle = pid.update(error, dt);

    double forwardFactor = computeForwardFactor();
    double speed         = speedCtrl.update(angle, forwardFactor);

    emit deplacer(0.15, angle);
    sendDebugInfo(speed, error); // Ici on envoie la vitesse réelle calculée
}

void Controleur::onFrontStableTimeout()
{
    // déclenché après stableDurationMs sans variation
    reverseTimer.restart();
    double sumL = sumRange(distances_mm,  60, 170);
    double sumR = sumRange(distances_mm, 190, 300);

    if (sumL < seuilSideClear && sumR < seuilSideClear) {
        revPhase = ReversePhase::Straight;
    } else {
        revPhase      = ReversePhase::Turn1;
        turnLeftFirst = (sumL > sumR);
    }
}

bool Controleur::handleReverseDetection()
{
    if (revPhase != ReversePhase::Idle)
        return false;

    // Lire les NBEAMS distances autour de 180°
    std::array<double, NBEAMS> current;
    for (int k = 0; k < NBEAMS; ++k) {
        int idx = (180 + BEAM_OFFSETS[k] + 360) % 360;
        current[k] = static_cast<double>(distances_mm[idx]);
    }

    // Initialisation au premier passage
    if (std::isnan(prevFrontDists[0])) {
        prevFrontDists = current;
        frontStableTimer.stop();
        return false;
    }

    // On regarde si au moins un faisceau est stable
    bool anyStable = false;
    for (int k = 0; k < NBEAMS; ++k) {
        if (std::abs(current[k] - prevFrontDists[k]) <= changeThresholdMm) {
            anyStable = true;
            break;
        }
    }

    if (anyStable) {
        if (!frontStableTimer.isActive())
            frontStableTimer.start(stableDurationMs);
    } else {
        frontStableTimer.stop();
    }

    prevFrontDists = current;
    return false;
}

void Controleur::handleReverseMovement()
{
    if (revPhase == ReversePhase::Straight) {
        double sumL = sumRange(distances_mm,  60, 120);
        double sumR = sumRange(distances_mm, 240, 300);
        if (sumL >= seuilSideClear || sumR >= seuilSideClear) {
            revPhase      = ReversePhase::Turn1;
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

    // Valeur de substitution si le LIDAR ne voit rien (voie libre)
    const double DISTANCE_MAX = 4000.0;

    // ON CHANGE LA FENÊTRE : De 30° à 85°
    // 0° à 30° (tout droit) est IGNORÉ pour ne pas anticiper.
    // 30° à 85° regarde en diagonale jusqu'au côté strict du robot.
    for (int i = 30; i <= 85; ++i) {
        double rad = M_PI * i / 180.0;

        double distR = distances_mm[180 + i];
        double distL = distances_mm[180 - i];

        // Sécurité contre les "trous" du LIDAR (noir = pas de retour)
        if (distR <= 0 || distR > DISTANCE_MAX) distR = DISTANCE_MAX;
        if (distL <= 0 || distL > DISTANCE_MAX) distL = DISTANCE_MAX;

        // Calcul des poids : sin(rad) favorise ÉNORMÉMENT les côtés (proche de 90°)
        // et donne moins d'importance à l'avant (proche de 30°).
        errR += std::sin(rad) * distR;
        errL += std::sin(rad) * distL;
    }

    return errR - errL;
}

double Controleur::computeForwardFactor() const
{
    double sum = 0.0, weightSum = 0.0;
    for (int i = -20; i <= 20; ++i) {
        int index = (180 + i + 360) % 360;
        double angleRad = i * M_PI / 180.0;
        double weight = std::pow(std::cos(angleRad), 2);
        sum += weight * distances_mm[index];
        weightSum += weight;
    }
    double meanDist = sum / weightSum;
    constexpr double seuilBas  = 1800.0;
    constexpr double seuilHaut = 6000.0;
    double factor = (meanDist - seuilBas) / (seuilHaut - seuilBas);
    return std::clamp(factor, 0.0, 1.0);
}

// <--- Modifié pour inclure la vitesse réelle émise
void Controleur::sendDebugInfo(double vitesseEmise, double error)
{
    QString debug = QString("Vitesse=%1 | Err=%2 | P=%3 | I=%4 | D=%5 | FwdFact=%6")
                        .arg(vitesseEmise,             0, 'f', 2)
                        .arg(error,                    0, 'f', 2)
                        .arg(pid.lastP,                0, 'f', 2)
                        .arg(pid.lastI,                0, 'f', 2)
                        .arg(pid.lastD,                0, 'f', 2)
                        .arg(computeForwardFactor(),   0, 'f', 2);

    qDebug() << debug;
    emit sendAffichage(debug); // Envoi à l'interface graphique (TCP)
}

double Controleur::sumRange(const std::array<int,360>& D, int start, int end, int step)
{
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
    if      (message == "on")           isRunning = true;
    else if (message == "off")          isRunning = false;
    else if (message == "test_angle")   testBoucleDirection();
    else if (message == "test_vitesse") testBoucleVitesse();
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

// <--- Modifié pour plafonner le test à 0.60
void Controleur::testBoucleVitesse()
{
    double angle = 0.0, step = 0.05, vitesse = 0.0;
    while (vitesse <= 0.6) {
        emit deplacer(vitesse, angle);
        QString info = QString("Test -> V:%1 | A:%2").arg(vitesse).arg(angle);
        emit sendAffichage(info);
        qDebug() << info;
        vitesse += step;
        QThread::msleep(300);
    }
    vitesse = 0.6 - step;
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
