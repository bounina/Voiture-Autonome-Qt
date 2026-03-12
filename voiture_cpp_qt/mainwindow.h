#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QObject>
//#include "materielsimule.h"
#include "clienttcp.h"
#include "controleur.h"
#include <QTcpServer>
#include "serveurtcp.h"
#include "materielreel.h"


class MainWindow : public QObject
{
    Q_OBJECT

public:
    MainWindow(QObject *parent=nullptr);
    ~MainWindow();
public slots :

signals:
        void envoyer(QString message);
private:
    Controleur c1;
    ServeurTcp s1;
    MaterielReel mr1;
//    MaterielSimule m1;

};
#endif // MAINWINDOW_H
