#include "i2c.h"

#include <fcntl.h>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cerrno>
#include <unistd.h>
#include <linux/i2c.h>
extern "C" { 
    #include <linux/i2c-dev.h>
    #if 0 
    #include <i2c/smbus.h>
    #endif
}
#include <sys/ioctl.h>

/* initialize the i2c structure by opening the i2c device file and storing the file descriptor in the structure */
int i2c_init(i2c_t *i2c, const char *device) {
    // open the i2c device file and store the file descriptor in the i2c structure
    i2c->fd = open(device,O_RDWR); // O_RDWR : open for reading and writing

    // check if the opening failed, which will return -1
    if (i2c->fd < 0){
        glog.log("I2C: Failed to open %s: %s\n", device, strerror(errno));
        return 1;
    } 
    
    // initialize the slave address to 0, which is invalid, 
    // so that the first time we do an i2c operation, 
    // it will set the slave address correctly
    i2c->slave = 0;
    return 0;
}

/* Close I2C bus */
int i2c_free(i2c_t *i2c) {
    // close the file descriptor
    if (close(i2c->fd) < 0){
        glog.log("I2C: Failed to close i2c device: %s\n", strerror(errno));
        return 1;
    }
    return 0;
}

/* Basic read */
int i2c_read(i2c_t *i2c, uint8_t slave, uint8_t *buf, size_t len){
    i2c->slave = 0xFF; // resetting your struct’s cached field

    // target slave address : slave
    // flags : I2C_M_RD means read operation
    // length of the data to be read : len
    // pointer to the buffer to store the read data : buf
    i2c_msg message = {slave, I2C_M_RD, (uint16_t)len, buf}; // create an i2c_msg structure to represent the read 
    
    // create an i2c_rdwr_ioctl_data structure to represent the ioctl data for the I2C_RDWR command, 
    // which contains a pointer to the i2c_msg structure and 
    // the number of messages (1 in this case)
    i2c_rdwr_ioctl_data ioctl_data = { &message, 1 };

    // this is the only part that acrually performs the i2c read operation by using ioctl with I2C_RDWR command,
    // and passing the ioctl_data structure as the argument, which contains the information about the read
    int res = ioctl(i2c->fd, I2C_RDWR, &ioctl_data);

    // if the operation of ioctl returns -1, it means the read operation failed, and we log the error message
    if (res < 0) {
        glog.log("i2c_read failed %s\n",std::strerror(errno));
    }
    return res;
}

/* Basic write */
int i2c_write(i2c_t *i2c, uint8_t slave, uint8_t *buf, size_t len){
    i2c->slave = 0xFF; //resetting your struct’s cached field

    // target slave address : slave
    // flags : 0 means write operation
    // length of the data to be written : len
    // pointer to the buffer that contains the data to be written : buf
    i2c_msg message = {slave, 0, (uint16_t)len, buf}; // create an i2c_msg structure to represent the write

    // create an i2c_rdwr_ioctl_data structure to represent the ioctl data for the I2C_RDWR command, 
    // which contains a pointer to the i2c_msg structure and
    // the number of messages (1 in this case)
    i2c_rdwr_ioctl_data ioctl_data = { &message, 1 };

    // this is the only part that acrually performs the i2c write operation by using ioctl with I2C_RDWR command,
    // and passing the ioctl_data structure as the argument, which contains the information about the write
    int res = ioctl(i2c->fd, I2C_RDWR, &ioctl_data);

    // if the operation of ioctl returns -1, it means the write operation failed, and we log the error message
    if (res < 0) {
       glog.log("i2c_write failed %s\n",std::strerror(errno));
    }
    return res;
}

/* Convenience helpers  */
// assumption : first byte sets register address, second byte is the data to be written to that register
int i2c_reg_read(i2c_t *i2c, uint8_t slave, uint8_t reg) {

    // because slave device cannot know which register we want to read from, 
    // we need to write the register address to the slave first, then read the data from the slave
    uint8_t wbuf[1] = {reg}; // the data to send to the slave, which is the register address we want to read from
    uint8_t rbuf[1]; // the buffer to store the read data from the slave

    // this will write the register address to the slave, then read 1 byte of data from the slave
    int ret = i2c_writeread(i2c, slave, wbuf, 1, rbuf, 1);
    if (ret < 0)
        return -1;

    return rbuf[0];
}

/* Convenience helpers  */
// assumption : first byte sets register address, second byte is the data to be written to that register
int i2c_reg_write(i2c_t *i2c, uint8_t slave, uint8_t reg, uint8_t data) {
    // write the register address to the slave, then read 1 byte of data from the slave
    uint8_t buf[2];
    buf[0] = reg;
    buf[1] = data;
    // this will write the register address to the slave]
    return i2c_write(i2c, slave, buf, 2);
}


/* Read register, then write data */
int i2c_readwrite(i2c_t *i2c, uint8_t slave, uint8_t *rbuf, size_t rlen, uint8_t *wbuf, size_t wlen) {
    i2c->slave = 0xFF; //resetting your struct’s cached field

    // maiking an array of i2c_msg structures (pre-defined) to represent the read and write operations
    
    // for the read operation
    // target slave address : salve
    // flags : I2C_M_RD means read operation
    // length of the data to be read : rlen
    // pointer to the buffer to store the read data : rbuf
                
    // for the write operation
    // target slave address : salve
    // flags : 0 means write operation
    // length of the data to be written : wlen
    // pointer to the buffer that contains the data to be written : wbuf

    i2c_msg msg[2] = {{slave, I2C_M_RD, (uint16_t)rlen, rbuf}, {slave, 0, (uint16_t)wlen, wbuf}};
                       
    // create an i2c_rdwr_ioctl_data structure to represent the ioctl data for the I2C_RDWR command
    i2c_rdwr_ioctl_data ioctl_data = { msg, 2 };
    
    // this is the only part that acrually performs the i2c read and write operations by using ioctl with I2C_RDWR command
    int res = ioctl(i2c->fd, I2C_RDWR, &ioctl_data);

    // if the operation of ioctl returns -1, it means the read/write operation failed, and we log the error message
    if (res < 0) {
        glog.log("i2c_readwrite failed %s\n",std::strerror(errno));
    }
    return res;
}

/* Write register, then read data */
int i2c_writeread(i2c_t *i2c, uint8_t slave, uint8_t *wbuf, size_t wlen, uint8_t *rbuf, size_t rlen) {
    i2c->slave = 0xFF; 

    // the same thing as i2c_readwrite, but the order of the read and write operations is reversed
    // for detils, check the comments in the implementation of i2c_readwrite above
    i2c_msg msg[2] = {{slave, 0, (uint16_t)wlen, wbuf}, {slave, I2C_M_RD, (uint16_t)rlen, rbuf}};
    
    // create an i2c_rdwr_ioctl_data structure to represent the ioctl data for the I2C_RDWR command
    i2c_rdwr_ioctl_data ioctl_data = { msg, 2 };

    // this is the only part that acrually performs the i2c read and write operations by using ioctl with I2C_RDWR command
    int res = ioctl(i2c->fd, I2C_RDWR, &ioctl_data);

    // if the operation of ioctl returns -1, it means the read/write operation failed, and we log the error message
    if (res < 0) {
        glog.log("i2c_writeread failed %s\n",std::strerror(errno));
    }
    return res;
}
