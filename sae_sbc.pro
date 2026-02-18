QT       += core gui network

greaterThan(QT_MAJOR_VERSION, 4): QT += widgets

CONFIG += c++17

# You can make your code fail to compile if it uses deprecated APIs.
# In order to do so, uncomment the following line.
# DEFINES += QT_DISABLE_DEPRECATED_BEFORE=0x060000    # disables all the APIs deprecated before Qt 6.0.0

SOURCES += \
    clienttcp.cpp \
    controleur.cpp \
    main.cpp \
    mainwindow.cpp \
    materiel.cpp \
    materielreel.cpp \
    pwm.cpp \
    serveurtcp.cpp \
    servomoteur.cpp \
    tfmini.cpp

HEADERS += \
    clienttcp.h \
    controleur.h \
    mainwindow.h \
    materiel.h \
    materielreel.h \
    materielsimule.h \
    pwm.h \
    serveurtcp.h \
    servomoteur.h \
    tfmini.h

FORMS += \
    mainwindow.ui

# ======================================================================
# CONFIGURATION LIDAR (CHEMIN RELATIF S�CURIS�)
# ======================================================================
# $$PWD repr�sente le dossier contenant ce fichier .pro
# $$PWD/../../rplidar_sdk remonte de 2 crans pour trouver le SDK
LIDAR_SDK_PATH = $$PWD/../../rplidar_sdk

unix:!macx: LIBS += -L$$LIDAR_SDK_PATH/output/Linux/Release/ -lsl_lidar_sdk
# LIBS += -li2c

INCLUDEPATH += $$LIDAR_SDK_PATH/sdk/include
INCLUDEPATH += $$LIDAR_SDK_PATH/sdk/src
DEPENDPATH  += $$LIDAR_SDK_PATH/sdk/include

unix:!macx: PRE_TARGETDEPS += $$LIDAR_SDK_PATH/output/Linux/Release/libsl_lidar_sdk.a
# ======================================================================

# Default rules for deployment.
qnx: target.path = /tmp/$${TARGET}/bin
else: unix:!android: target.path = /opt/$${TARGET}/bin
!isEmpty(target.path): INSTALLS += target

DISTFILES += \
    sae.qmodel
