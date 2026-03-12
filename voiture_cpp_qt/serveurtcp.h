#ifndef SERVEURTCP_H
#define SERVEURTCP_H
#include <QTcpServer>
#include <QTcpSocket>
#include <QDataStream>
#include <QString>

class ServeurTcp : public QObject
{
    Q_OBJECT

public:
    ServeurTcp(int _port);

private :
    QTcpServer monServeur;
    QTcpSocket * serveurSocket = nullptr;
    QDataStream dataIn;
    int port;

public slots:
    void sendDatas(QString);


private slots:
    void newConnexion();
    void getDatas();

signals :
    void newDatas(QString);

};

#endif // SERVEURTCP_H








