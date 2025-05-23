#include "mainwindow.h"
#include <QTcpServer>
#include <QTcpSocket>


MainWindow::MainWindow(QObject *parent)
    : QObject(parent)
    , c1(mr1.distances_mm)
    , s1(8884)


{
// c1.initPID(0.0000013,0.0000006);

    c1.initPID(0.000035,0.0,0.0, 0.0);
    // A TESTER c1.initPID(0.00008, 0.00011); !




//     connect(&c1, &Controleur::deplacer,
//             &m1, &MaterielSimule::deplacer);
//     connect(&m1, &MaterielSimule::newDatas,
//             &c1, &Controleur::newDatas);

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








