// Controleur.h
#ifndef CONTROLEUR_H
#define CONTROLEUR_H

#include <QObject>
#include <QElapsedTimer>
#include <QString>
#include <array>
#include <cmath>
#include <algorithm>

class Controleur : public QObject {
    Q_OBJECT

public:
    explicit Controleur(std::array<int,360>& distancesMm, QObject* parent = nullptr);
    void initPID(double kp, double ki, double kd);

public slots:
    void newDatas();
    void conversion();
    void onoff(const QString& message);
    void onTfminiDistance(int dist_cm);    // <— slot pour mise à jour TFmini

signals:
    void deplacer(double vitesse, double angle);
    void sendAffichage(const QString& info);
    void donneeconvertion(const QString& data);

private:
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

    struct SpeedController {
        double currentSpeed{0.0};
        double update(double angle) {
            double factor = std::fabs(angle);
            double target = vmin + (vmax - vmin) * (1.0 - factor);
            if (target > currentSpeed)
                currentSpeed += accelFact * (target - currentSpeed);
            else
                currentSpeed += decelFact * (target - currentSpeed);
            currentSpeed = std::clamp(currentSpeed, vmin, vmax);
            return currentSpeed;
        }
    };

    bool handleReverseDetection();
    void handleReverseMovement();
    double computeError() const;
    void sendDebugInfo(double vTarget, double error);

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
    SpeedController speedCtrl;

    // ** TFmini **
    int tfminiDistCm{1000};  // dernière mesure TFmini en cm

    // Constantes de configuration
    static constexpr double seuilReverse    = 175.0;
    static constexpr double seuilSideClear  = 175.0;
    static constexpr double vitesseReverse  = -0.35;
    static constexpr int    phase1Ms        = 1000;
    static constexpr int    phase2Ms        = 200;
    static constexpr double angleS          = 1.0;
    static constexpr double vmax            = 0.60;
    static constexpr double vmin            = 0.35;
    static constexpr double accelFact       = 0.03;
    static constexpr double decelFact       = 0.1;
};

#endif // CONTROLEUR_H
