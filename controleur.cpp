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

    // ========== TÉLÉOPÉRATION MANUELLE ==========
    // Quand modeManuel est actif, on envoie directement les consignes
    // manuelles et on court-circuite toute la boucle PID.
    if (modeManuel) {
        emit deplacer(manualSpeed, manualAngle);
        return;
    }
    // ========== FIN TÉLÉOPÉRATION ==========

    // --- Conduite autonome (PID) --- conservée intacte pour usage futur ---
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
    // Commandes de téléopération manuelle (préfixe TELEOP:)
    if (message.startsWith("TELEOP:")) {
        handleManualCommand(message);
        return;
    }

    // Commandes existantes (on/off/test)
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

// ========== TÉLÉOPÉRATION MANUELLE ==========
void Controleur::handleManualCommand(const QString& cmd)
{
    // Active automatiquement le running + mode manuel
    isRunning  = true;
    modeManuel = true;

    // --- Commande continue : TELEOP:DRIVE,speed,angle ---
    if (cmd.startsWith("TELEOP:DRIVE,")) {
        QStringList parts = cmd.mid(13).split(',');  // après "TELEOP:DRIVE,"
        if (parts.size() == 2) {
            bool okV, okA;
            double v = parts[0].toDouble(&okV);
            double a = parts[1].toDouble(&okA);
            if (okV && okA) {
                manualSpeed = std::clamp(v, -1.0, 1.0);
                manualAngle = std::clamp(a, -1.0, 1.0);
                emit deplacer(manualSpeed, manualAngle);

                // Log réduit (1 message sur 20 pour ne pas spammer)
                static int driveLogCounter = 0;
                if (++driveLogCounter % 20 == 0) {
                    qDebug() << "[TELEOP] DRIVE -> V:" << manualSpeed << "A:" << manualAngle;
                }
                return;
            }
        }
        qDebug() << "[TELEOP] DRIVE format invalide:" << cmd;
        return;
    }

    // --- Test servo : sweep de -1 à +1 pour diagnostic ---
    if (cmd == "TELEOP:TEST_SERVO") {
        qDebug() << "[TELEOP] === TEST SERVO START ===";
        manualSpeed = 0.0;  // pas de mouvement pendant le test

        // Sweep de -1.0 à +1.0 par pas de 0.2 avec pause
        for (double testAngle = -1.0; testAngle <= 1.0; testAngle += 0.2) {
            manualAngle = testAngle;
            emit deplacer(0.0, manualAngle);
            qDebug() << "[TELEOP] TEST angle:" << testAngle;
            QThread::msleep(500);  // 500ms par position
        }
        // Retour au centre
        manualAngle = 0.0;
        emit deplacer(0.0, 0.0);
        qDebug() << "[TELEOP] === TEST SERVO END ===";
        return;
    }

    // --- Commandes discrètes (rétrocompatibilité) ---
    if (cmd == "TELEOP:FWD") {
        manualSpeed = MANUAL_FWD_SPEED;
    }
    else if (cmd == "TELEOP:BWD") {
        manualSpeed = MANUAL_BWD_SPEED;
    }
    else if (cmd == "TELEOP:LEFT") {
        manualAngle = std::clamp(manualAngle - ANGLE_STEP, -1.0, 1.0);
    }
    else if (cmd == "TELEOP:RIGHT") {
        manualAngle = std::clamp(manualAngle + ANGLE_STEP, -1.0, 1.0);
    }
    else if (cmd == "TELEOP:STOP") {
        manualSpeed = 0.0;
        manualAngle = 0.0;
    }
    else {
        qDebug() << "[TELEOP] Commande inconnue:" << cmd;
        return;
    }

    qDebug() << "[TELEOP]" << cmd << "-> V:" << manualSpeed << "A:" << manualAngle;
    emit deplacer(manualSpeed, manualAngle);
}
