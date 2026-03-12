// TFmini.h
#ifndef TFMINI_H
#define TFMINI_H
#include <cstdint>
#include <string>

class TFmini {
public:
    TFmini(int i2c_address = 0x10, const std::string& i2c_device = "/dev/i2c-1");
    ~TFmini();

    bool init();
    int getDistance();

private:
    int address_;
    std::string i2c_device_;
    int file_;
};

#endif // TFMINI_H
