#include "ptc.h"
#include <iostream>
#include <iomanip>

int main() {
    PTC ptc;

    int val8  = ptc.read_i2c_reg(3, 0x48, 0x00);
    int val16 = ptc.read_i2c_reg16(3, 0x48, 0x00);

    std::cout << "read_i2c_reg(3, 0x48, 0x00)   = 0x"
              << std::hex << val8 << std::endl;

    std::cout << "read_i2c_reg16(3, 0x48, 0x00) = 0x"
              << std::hex << val16 << std::endl;

    return 0;
}
