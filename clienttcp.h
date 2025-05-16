#ifndef CLIENTTCP_H
#define CLIENTTCP_H
#include <QTcpSocket>
#include<QDataStream>
#include <QObject>
#include<QString>
#include<QTimer>
#include<QThread>
class ClientTCP : public QObject
{
    Q_OBJECT
public:
    explicit ClientTCP(QString _addressIp, int _port );
private:
    QTcpSocket clientSocket;
    QDataStream dataIn ;
    QTimer tictoc;
    QString addressIp;
    int port;
    void connectToHost();


public slots:
    void sendDatas(QString message);
    void getDatas();

private slots:
    void connexion();
    void deconnexion();

signals:
    void newDatas(QString);

};

#endif // CLIENTTCP_H
