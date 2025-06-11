#include "tfmini.h"
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstdint>

TFmini::TFmini(int i2c_address, const std::string& i2c_device) :
    address_(i2c_address),
    i2c_device_(i2c_device),
    file_(0)
{}

TFmini::~TFmini() {
    close(file_);
}

bool TFmini::init() {
    if ((file_ = open(i2c_device_.c_str(), O_RDWR)) < 0) {
        std::cerr << "Failed to open I2C bus." << std::endl;
        return false;
    }
    if (ioctl(file_, I2C_SLAVE, address_) < 0) {
        std::cerr << "Failed to acquire bus access and/or talk to slave." << std::endl;
        return false;
    }
    return true;
}

int TFmini::getDistance() {
    uint8_t data[9];
    if (read(file_, data, 9) != 9) {
        std::cerr << "Error reading data from TFmini." << std::endl;
        return -1;
    }

    if (data[0] != 0x59 || data[1] != 0x59) {
        std::cerr << "Invalid frame header." << std::endl;
        return -1;
    }

    uint16_t dist = (data[2] << 8) + data[3];
    uint8_t checksum = 0;
    for (int i = 0; i < 8; i++) {
        checksum += data[i];
    }

    if (checksum != data[8]) {
        std::cerr << "Checksum error." << std::endl;
        return -1;
    }
    return dist;
}
