#include "mainwindow.h"
#include <QTcpServer>
#include <QTcpSocket>


MainWindow::MainWindow(QObject *parent)
    : QObject(parent)
    , c1(mr1.distances_mm)
    , s1(8884)


{

//    c1.initPID(
//        (0.00000922 - ((c1.speedCtrl.currentSpeed-0.35)/245000)),
//                                                     //+ grand = reduit avec + de vitesse
//        0.000000,
//        0.00000036
//        );

    c1.initPID(0.00002, 0.0, 0.000);
    connect(&mr1, &MaterielReel::tfminiDistanceChanged,
            &c1 ,   &Controleur::onTfminiDistance);


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
