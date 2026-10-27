#include "ptc.h"
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

struct ReadSpec {
    uint8_t mux;
    uint8_t addr;
    uint8_t reg;
    std::string label;
};

static void print_result(uint8_t mux, uint8_t addr, uint8_t reg,
                         const std::string& label, int val, bool is16)
{
    std::cout << "mux=" << std::dec << static_cast<int>(mux)
              << " addr=0x" << std::hex << std::setw(2) << std::setfill('0')
              << static_cast<int>(addr)
              << " reg=0x" << std::setw(2)
              << static_cast<int>(reg)
              << "  ";

    if (val < 0) {
        std::cout << "ERROR";
    } else if (is16) {
        std::cout << "0x" << std::setw(4) << (val & 0xffff);
    } else {
        std::cout << "0x" << std::setw(2) << (val & 0xff);
    }

    std::cout << "   " << label << std::endl;
}

int main() {
    PTC ptc;

    // Things we most want to probe based on your scans + old scripts
    std::vector<ReadSpec> tests16 = {
        // mux 0x08 branch = channel 3 in your current code
        {3, 0x48, 0x00, "temp? sensor 0x48"},
        {3, 0x49, 0x00, "temp? sensor 0x49"},
        {3, 0x4a, 0x00, "temp? sensor 0x4a"},

        {3, 0x6d, 0x1e, "volt/current monitor? V register"},
        {3, 0x6d, 0x14, "volt/current monitor? I register"},
        {3, 0x6e, 0x1e, "48V monitor? V register"},
        {3, 0x6e, 0x14, "48V monitor? I register"},

        // devices seen on mux 0x01 = channel 0
        {0, 0x50, 0x00, "EEPROM?/memory? register 0x00"},
        {0, 0x51, 0x00, "EEPROM?/memory? register 0x00"},
        {0, 0x56, 0x00, "EEPROM?/memory? register 0x00"},

        // always-visible / unclear
        {3, 0x64, 0x00, "unknown device 0x64 reg 0x00"},
        {3, 0x66, 0x00, "unknown device 0x66 reg 0x00"},
        {3, 0x66, 0x1e, "unknown device 0x66 reg 0x1e"},
        {3, 0x66, 0x14, "unknown device 0x66 reg 0x14"},
    };

    std::cout << "===== 8-bit sanity reads =====" << std::endl;
    for (const auto& t : tests16) {
        int val8 = ptc.read_i2c_reg(t.mux, t.addr, t.reg);
        print_result(t.mux, t.addr, t.reg, t.label, val8, false);
    }

    std::cout << "\n===== 16-bit reads =====" << std::endl;
    for (const auto& t : tests16) {
        int val16 = ptc.read_i2c_reg16(t.mux, t.addr, t.reg);
        print_result(t.mux, t.addr, t.reg, t.label, val16, true);
    }

    return 0;
}
