#ifndef MATERIELSIMULE_H
#define MATERIELSIMULE_H

#include "materiel.h"
#include "controleur.h"
#include "clienttcp.h"
#include <QString>

class MaterielSimule : public Materiel
{
public:
    MaterielSimule();
    ClientTCP tcp{"10.98.32.154",8880};


public slots:
    void processTcpDatas(QString data);
    virtual void deplacer(double _vitesse, double _angle) override;
};

#endif // MATERIELSIMULE_H
