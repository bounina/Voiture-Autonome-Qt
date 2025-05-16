#ifndef MATERIEL_H
#define MATERIEL_H

#include <QObject>
#include <array>
using namespace std;

class Materiel : public QObject
{
    Q_OBJECT
public:
    Materiel();
    array<int,360> distances_mm;

protected:


public slots:
    virtual void deplacer(double _vitesse, double _angle)=0;

signals:
    void newDatas();
    void sendAffichage(QString envoi);

};

#endif // MATERIEL_H
