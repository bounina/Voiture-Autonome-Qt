#include "mainwindow.h"
#include <QTcpServer>
#include <QTcpSocket>


MainWindow::MainWindow(QObject *parent)
    : QObject(parent)
    , c1(mr1.distances_mm)
    , s1(8884)


{

    c1.initPID(
        0.000013,
        0.00001,
        0.000005
        );

    connect(&mr1, &MaterielReel::newDatas,
            &c1, &Controleur::newDatas);
    connect(&mr1, &MaterielReel::newDatas,
            &c1, &Controleur::conversion);

    connect(&c1, &Controleur::donneeconvertion,
            &s1, &ServeurTcp::sendDatas);
    connect(&c1, &Controleur::sendAffichage,
            &s1, &ServeurTcp::sendDatas);
    connect(&s1, &ServeurTcp::newDatas,
            &c1, &Controleur::onoff);

    connect(&c1, &Controleur::deplacer,
            &mr1, &MaterielReel::deplacer);

}


MainWindow::~MainWindow()
{
}








