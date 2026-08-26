#include "i2c.h"
#include <cstdio>
#include <cstdint>

int main() {
    i2c_t i2c;

    // Open the correct bus (IMPORTANT: i2c-1, not 0)
    if (i2c_init(&i2c, "/dev/i2c-1") != 0) {
        printf("Failed to initialize I2C\n");
        return 1;
    }

    printf("Testing device at address 0x64 on /dev/i2c-1...\n");

    uint8_t val = i2c_reg_read(&i2c, 0x64, 0x00);
    printf("Register 0x00 = %d\n", val);

    i2c_free(&i2c);
    return 0;
}
