/********************************************************************************
** Form generated from reading UI file 'mainwindow.ui'
**
** Created by: Qt User Interface Compiler version 5.15.15
**
** WARNING! All changes made in this file will be lost when recompiling UI file!
********************************************************************************/

#ifndef UI_MAINWINDOW_H
#define UI_MAINWINDOW_H

#include <QtCore/QVariant>
#include <QtWidgets/QApplication>
#include <QtWidgets/QLabel>
#include <QtWidgets/QMainWindow>
#include <QtWidgets/QMenuBar>
#include <QtWidgets/QPushButton>
#include <QtWidgets/QStatusBar>
#include <QtWidgets/QWidget>
#include "widgetlidar.h"

QT_BEGIN_NAMESPACE

class Ui_MainWindow
{
public:
    QWidget *centralwidget;
    QPushButton *bp_on;
    QPushButton *bp_off;
    QLabel *affichage;
    QLabel *affichage2;
    WidgetLIDAR *wiwi;
    QMenuBar *menubar;
    QStatusBar *statusbar;

    void setupUi(QMainWindow *MainWindow)
    {
        if (MainWindow->objectName().isEmpty())
            MainWindow->setObjectName(QString::fromUtf8("MainWindow"));
        MainWindow->resize(800, 600);
        centralwidget = new QWidget(MainWindow);
        centralwidget->setObjectName(QString::fromUtf8("centralwidget"));
        bp_on = new QPushButton(centralwidget);
        bp_on->setObjectName(QString::fromUtf8("bp_on"));
        bp_on->setGeometry(QRect(370, 30, 151, 71));
        bp_off = new QPushButton(centralwidget);
        bp_off->setObjectName(QString::fromUtf8("bp_off"));
        bp_off->setGeometry(QRect(570, 30, 151, 71));
        affichage = new QLabel(centralwidget);
        affichage->setObjectName(QString::fromUtf8("affichage"));
        affichage->setGeometry(QRect(110, 50, 251, 111));
        affichage2 = new QLabel(centralwidget);
        affichage2->setObjectName(QString::fromUtf8("affichage2"));
        affichage2->setGeometry(QRect(90, 220, 251, 111));
        wiwi = new WidgetLIDAR(centralwidget);
        wiwi->setObjectName(QString::fromUtf8("wiwi"));
        wiwi->setGeometry(QRect(370, 110, 381, 351));
        MainWindow->setCentralWidget(centralwidget);
        menubar = new QMenuBar(MainWindow);
        menubar->setObjectName(QString::fromUtf8("menubar"));
        menubar->setGeometry(QRect(0, 0, 800, 22));
        MainWindow->setMenuBar(menubar);
        statusbar = new QStatusBar(MainWindow);
        statusbar->setObjectName(QString::fromUtf8("statusbar"));
        MainWindow->setStatusBar(statusbar);

        retranslateUi(MainWindow);

        QMetaObject::connectSlotsByName(MainWindow);
    } // setupUi

    void retranslateUi(QMainWindow *MainWindow)
    {
        MainWindow->setWindowTitle(QCoreApplication::translate("MainWindow", "MainWindow", nullptr));
        bp_on->setText(QCoreApplication::translate("MainWindow", "Bp On", nullptr));
        bp_off->setText(QCoreApplication::translate("MainWindow", "Bp Off", nullptr));
        affichage->setText(QCoreApplication::translate("MainWindow", "TextLabel", nullptr));
        affichage2->setText(QCoreApplication::translate("MainWindow", "TextLabel", nullptr));
    } // retranslateUi

};

namespace Ui {
    class MainWindow: public Ui_MainWindow {};
} // namespace Ui

QT_END_NAMESPACE

#endif // UI_MAINWINDOW_H
