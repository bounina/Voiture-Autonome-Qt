// controleur.h
#ifndef CONTROLEUR_H
#define CONTROLEUR_H

#include <QObject>
#include <QElapsedTimer>
#include <QTimer>
#include <QString>
#include <array>
#include <cmath>
#include <algorithm>
#include <limits>

class Controleur : public QObject {
    Q_OBJECT

public:
    explicit Controleur(std::array<int,360>& distancesMm, QObject* parent = nullptr);
    void initPID(double kp, double ki, double kd);

    struct SpeedController {
        double currentSpeed{0.0};
        double update(double angle, double forwardFactor) {
            double angleFactor = std::fabs(angle);
            double target = vmin + (vmax - vmin) * (1.0 - angleFactor) * forwardFactor;
            if (target > currentSpeed)
                currentSpeed += accelFact * (target - currentSpeed);
            else
                currentSpeed += (decelFact - 1.0 / ((currentSpeed - 0.34) * 80.0)) * (target - currentSpeed);

            currentSpeed = std::clamp(currentSpeed, vmin, vmax);
            return currentSpeed;
        }
    };

    SpeedController speedCtrl;

public slots:
    void newDatas();
    void conversion();
    void onoff(const QString& message);
    void onTfminiDistance(int dist_cm);    // slot pour mise à jour TFmini

private slots:
    void onFrontStableTimeout();   // déclenché après stableDurationMs

signals:
    void deplacer(double vitesse, double angle);
    void sendAffichage(const QString& info);
    void donneeconvertion(const QString& data);

private:
    static constexpr int   NBEAMS = 5;
    static constexpr int   BEAM_OFFSETS[NBEAMS] = { -20, -10, 0, +10, +20 };
    std::array<double, NBEAMS> prevFrontDists {
        std::numeric_limits<double>::quiet_NaN(),
        std::numeric_limits<double>::quiet_NaN(),
        std::numeric_limits<double>::quiet_NaN(),
        std::numeric_limits<double>::quiet_NaN(),
        std::numeric_limits<double>::quiet_NaN()
    };

    // pour détection de front immobile
    double prevFrontDist = std::numeric_limits<double>::quiet_NaN();
    QTimer frontStableTimer;
    static constexpr int   stableDurationMs  = 1000;  // ms avant déclenchement du recul
    static constexpr double changeThresholdMm = 50.0;   // tolérance de variation

    enum class ReversePhase { Idle, Straight, Turn1, Turn2 };

    struct PID {
        double kp{0}, ki{0}, kd{0};
        double I{0}, prevErr{0};
        bool firstRun{true};
        double lastP{0}, lastI{0}, lastD{0};

        double update(double err, double dt) {
            if (firstRun) {
                prevErr   = err;
                firstRun  = false;
            }
            I += err * dt;
            if ((prevErr < 0 && err >= 0) || (prevErr > 0 && err <= 0))
                I = 0.0;

            double D     = (dt > 0.0) ? (err - prevErr) / dt : 0.0;
            double P     = kp * err;
            double Iterm = ki * I;
            double Dterm = kd * D;

            lastP = P; lastI = Iterm; lastD = Dterm;
            prevErr = err;

            return P + Iterm + Dterm;
        }
    };

    bool handleReverseDetection();
    void handleReverseMovement();
    double computeError() const;
    double computeForwardFactor() const;
    void sendDebugInfo(double vitesseEmise, double error); // <--- Modifié ici

    static double sumRange(const std::array<int,360>& D, int start, int end, int step = 10);
    void testBoucleDirection();
    void testBoucleVitesse();

    // --- membres ---
    std::array<int,360>& distances_mm;
    QElapsedTimer timer, reverseTimer;
    bool isRunning{false};
    ReversePhase revPhase{ReversePhase::Idle};
    bool turnLeftFirst{false};
    PID pid;

    // TFmini
    int tfminiDistCm{1000};

    // Constantes de configuration
    static constexpr double seuilReverse    = 100.0;
    static constexpr double seuilSideClear  = 100.0;
    static constexpr double vitesseReverse  = -0.10;
    static constexpr int    phase1Ms        = 400;
    static constexpr int    phase2Ms        = 150;
    static constexpr double angleS          = 1.0;

    // --- SECURITE DE DEMO ---
    static constexpr double vmax            = 0.60;    // <--- Bridé à 60%
    static constexpr double vmin            = 0.37;
    static constexpr double accelFact       = 0.4;
    static constexpr double decelFact       = 0.92;
};

#endif // CONTROLEUR_H
