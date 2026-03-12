#include "serveurtcp.h"
#include "mainwindow.h"
#include <QString>
#include <QThread>
#include <QDebug>



ServeurTcp::ServeurTcp(int _port) {
    port=_port;
    connect(&monServeur,&QTcpServer::newConnection,
             this,&ServeurTcp::newConnexion);
    bool resEcoute = monServeur.listen((QHostAddress::AnyIPv4),_port);
    if( resEcoute == true)
    {
        qDebug()<<"ecoute réussie";
    }
    else{
        qCritical()<<"error";
        exit(EXIT_FAILURE);
    }
}

void ServeurTcp::newConnexion()
{
    qDebug()<<"connexion d'un nouveau client";
    serveurSocket = monServeur.nextPendingConnection();
    connect(serveurSocket,&QTcpSocket::readyRead,
            this,&ServeurTcp::getDatas);
    dataIn.setDevice(serveurSocket);

}


void ServeurTcp::getDatas()
{
    if (serveurSocket != nullptr) {
        QByteArray data = serveurSocket->readAll();
        QString messages = QString::fromUtf8(data);
        QStringList list = messages.split('\n', Qt::SkipEmptyParts);

        for(int i = 0; i < list.size(); ++i) {
            QString msg = list.at(i).trimmed();
            if(!msg.isEmpty()) {
                emit newDatas(msg);
            }
        }
    }
}

void ServeurTcp::sendDatas(QString message)
{
    if(serveurSocket!=nullptr)
    {
        QByteArray block;
        QDataStream out(&block, QIODevice::WriteOnly);
        out.setVersion(QDataStream::Qt_5_0);
        out << message;
        // qDebug()<<"message envoyé :"<< message;
        serveurSocket->write(block);
    }
}



