#include "ptc.h"
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

struct ReadSpec {
    uint8_t mux;
    uint8_t addr;
    uint8_t reg;
    std::string label;
    enum Kind { TEMP_TMP117, MONITOR_LTC2945_V, MONITOR_LTC2945_I, RAW } kind;
};

static uint16_t bswap16(uint16_t x) {
    return static_cast<uint16_t>((x >> 8) | (x << 8));
}

static void print_header(const std::string& title) {
    std::cout << "\n===== " << title << " =====" << std::endl;
}

static void print_raw_result(const ReadSpec& t, int val16) {
    std::cout << "mux=" << std::dec << static_cast<int>(t.mux)
              << " addr=0x" << std::hex << std::setw(2) << std::setfill('0')
              << static_cast<int>(t.addr)
              << " reg=0x" << std::setw(2)
              << static_cast<int>(t.reg)
              << "  ";

    if (val16 < 0) {
        std::cout << "ERROR";
    } else {
        std::cout << "0x" << std::setw(4) << (val16 & 0xffff);
    }

    std::cout << "   " << t.label << std::endl;
}

static void print_decoded_result(const ReadSpec& t, int val16) {
    if (val16 < 0) return;

    uint16_t raw = static_cast<uint16_t>(val16 & 0xffff);

    switch (t.kind) {
        case ReadSpec::TEMP_TMP117: {
            // Older script notes i2cget word output is byte-swapped
            // and uses TMP117 scale 0.0078125 C/LSB.
            uint16_t swapped = bswap16(raw);
            double temp_c = static_cast<double>(swapped) * 0.0078125;
            std::cout << "    decoded TMP117-ish temperature: "
                      << std::fixed << std::setprecision(2)
                      << temp_c << " C" << std::endl;
            break;
        }

        case ReadSpec::MONITOR_LTC2945_V: {
            uint16_t swapped = bswap16(raw);
            uint16_t adc = swapped >> 4;
            double volts = static_cast<double>(adc) * 0.025;
            std::cout << "    decoded LTC2945-ish voltage: "
                      << std::fixed << std::setprecision(3)
                      << volts << " V" << std::endl;
            break;
        }

        case ReadSpec::MONITOR_LTC2945_I: {
            // Use 5 mΩ by default here; special-case 0x6e below
            uint16_t swapped = bswap16(raw);
            uint16_t adc = swapped >> 4;
            double shunt_ohm = (t.addr == 0x6e) ? 0.0025 : 0.0050;
            double current_a = static_cast<double>(adc) * 0.000025 / shunt_ohm;
            std::cout << "    decoded LTC2945-ish current: "
                      << std::fixed << std::setprecision(3)
                      << current_a << " A"
                      << "  (Rshunt=" << shunt_ohm << " ohm)" << std::endl;
            break;
        }

        case ReadSpec::RAW:
        default:
            break;
    }
}

int main() {
    PTC ptc;

    const std::vector<ReadSpec> tests = {
        {3, 0x48, 0x00, "TMP117 @ 0x48", ReadSpec::TEMP_TMP117},
        {3, 0x49, 0x00, "TMP117 @ 0x49", ReadSpec::TEMP_TMP117},
        {3, 0x4a, 0x00, "TMP117 @ 0x4a", ReadSpec::TEMP_TMP117},

        {3, 0x6d, 0x1e, "LTC2945 @ 0x6d : 12V rail voltage", ReadSpec::MONITOR_LTC2945_V},
        {3, 0x6d, 0x14, "LTC2945 @ 0x6d : 12V rail current", ReadSpec::MONITOR_LTC2945_I},
        {3, 0x6e, 0x1e, "LTC2945 @ 0x6e : 48V raile voltage", ReadSpec::MONITOR_LTC2945_V},
        {3, 0x6e, 0x14, "LTC2945 @ 0x6e : 48V rail current", ReadSpec::MONITOR_LTC2945_I},

        //{3, 0x64, 0x00, "unknown device 0x64", ReadSpec::RAW},
        //{3, 0x66, 0x00, "unknown device 0x66", ReadSpec::RAW},

        //{0, 0x50, 0x00, "memory/id device? 0x50", ReadSpec::RAW},
        //{0, 0x51, 0x00, "memory/id device? 0x51", ReadSpec::RAW},
        //{0, 0x56, 0x00, "memory/id device? 0x56", ReadSpec::RAW},
    };

    print_header("Raw 16-bit reads");
    for (const auto& t : tests) {
        int val16 = ptc.read_i2c_reg16(t.mux, t.addr, t.reg);
        print_raw_result(t, val16);
        print_decoded_result(t, val16);
    }

    // Extra experiment for 0x66: maybe it does not like register-style transactions.
    // Try just selecting the mux and leave further probing to Linux tools if needed.
    //print_header("Notes");
    //std::cout << "0x66 ACKs in i2cdetect but fails write-then-read register access." << std::endl;
    //std::cout << "Likely non-standard register protocol, different command format, or probe-only ACK." << std::endl;

    return 0;
}
