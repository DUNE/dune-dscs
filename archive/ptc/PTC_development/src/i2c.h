#ifndef i2c_h
#define i2c_h

// include the similar headders as i2c.h from wib_server, 
#include <cstdint>
#include <string>
#include <stdint.h>
#include "log.h"

// I2C device structure
typedef struct i2c_t {
	// file descriptor for the i2c device
	int fd; 
	// the currently selected slave address for this i2c device
	uint8_t slave; 
} i2c_t;


// init : initialization
int i2c_init(i2c_t *i2c, const char *device);
// freeing : cleaning up
int i2c_free(i2c_t *i2c);

// Basic read and write oiperation for i2c devices
// this reads/writes len bytes directlly from the slave into or from buf
// this does not tell the slave which register we want to read/write, so it is up to the caller to put the register address in the buf if needed
// this can also handle multi byte data, which is useful for some i2c devices that have multi byte registers
int i2c_read(i2c_t *i2c, uint8_t slave, uint8_t *buf, size_t len);
int i2c_write(i2c_t *i2c, uint8_t slave, uint8_t *buf, size_t len);

/* Write register, then read data */
/* Also, read register, then write data */
int i2c_readwrite(i2c_t *i2c, uint8_t slave, uint8_t *rbuf, size_t rlen, uint8_t *wbuf, size_t wlen);
int i2c_writeread(i2c_t *i2c, uint8_t slave, uint8_t *wbuf, size_t wlen, uint8_t *rbuf, size_t rlen);

/* Register Access */
// here, it assumes the device behaves like a register-mappewd I2C device, 
// which means we need to first write the register address to the slave, then read/write the data from/to the slave
// the register has to be 1 byte, and register data has to be 1 byte as well, which is the most common case for I2C devices
int i2c_reg_read(i2c_t *i2c, uint8_t slave, uint8_t reg);
int i2c_reg_write(i2c_t *i2c, uint8_t slave, uint8_t reg, uint8_t data);

#endif