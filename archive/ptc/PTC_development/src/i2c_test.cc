#include "ptc.h"
#include <iostream>
#include <iomanip>

int main() {
    PTC ptc;

    std::cout << std::fixed << std::setprecision(3);

    double t48 = ptc.read_tmp117_temp_c(3, 0x48);
    double t49 = ptc.read_tmp117_temp_c(3, 0x49);
    double t4a = ptc.read_tmp117_temp_c(3, 0x4a);

    double v6d = ptc.read_ltc2945_voltage_v(3, 0x6d);
    double i6d = ptc.read_ltc2945_current_a(3, 0x6d, 0.0050);

    double v6e = ptc.read_ltc2945_voltage_v(3, 0x6e);
    double i6e = ptc.read_ltc2945_current_a(3, 0x6e, 0.0025);

    std::cout << "TMP117 0x48 : " << t48 << " C\n";
    std::cout << "TMP117 0x49 : " << t49 << " C\n";
    std::cout << "TMP117 0x4a : " << t4a << " C\n";

    std::cout << "LTC2945 0x6d : " << v6d << " V, " << i6d << " A\n";
    std::cout << "LTC2945 0x6e : " << v6e << " V, " << i6e << " A\n";

    return 0;
}
