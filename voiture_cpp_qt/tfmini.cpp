// TFmini.cpp

#include "tfmini.h"

#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <iomanip>    // std::setw, std::setfill, std::hex

TFmini::TFmini(int i2c_address, const std::string& i2c_device)
    : address_(i2c_address),
    i2c_device_(i2c_device),
    file_(-1)
{}

TFmini::~TFmini() {
    if (file_ >= 0) close(file_);
}

bool TFmini::init() {
    file_ = open(i2c_device_.c_str(), O_RDWR);
    if (file_ < 0) {
        std::cerr << "TFmini: cannot open " << i2c_device_
                  << ": " << std::strerror(errno) << "\n";
        return false;
    }
    if (ioctl(file_, I2C_SLAVE, address_) < 0) {
        std::cerr << "TFmini: ioctl I2C_SLAVE failed: "
                  << std::strerror(errno) << "\n";
        close(file_);
        file_ = -1;
        return false;
    }
    return true;
}

int TFmini::getDistance() {
    // 1) Demande 7 octets à partir du registre 0x0102
    uint8_t cmd[3] = { 0x01, 0x02, 0x07 };
    if (write(file_, cmd, 3) != 3) {
        return -1;
    }

    // 2) Lecture brute (7 octets)
    uint8_t rx_buf[7] = {0};
    if (read(file_, rx_buf, sizeof(rx_buf)) != int(sizeof(rx_buf))) {
        return -1;
    }

    // 3) Vérifie que la mesure est fraîche
    if (rx_buf[0] != 0x01) {
        return -1;
    }

    // 4) Reconstruction de la distance EN CM
    //    Low  = rx_buf[2], High = rx_buf[3]
    uint16_t dist_cm = uint16_t(rx_buf[2]) | (uint16_t(rx_buf[3]) << 8);

    // 5) Filtrage par qualité (Strength Low = rx_buf[4], High = rx_buf[5])
    uint16_t strength = uint16_t(rx_buf[4]) | (uint16_t(rx_buf[5]) << 8);
    if (strength < 20) {
        return -1;
    }

    return int(dist_cm);
}

