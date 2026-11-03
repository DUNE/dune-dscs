#!/bin/bash
# PTC Build Script - Run from PTC_development/ root

echo "--- Step 1: Generating Protobuf Files (C++ and Python) ---"
# We generate them directly into src/
# --proto_path=src tells it to look for ptc.proto inside src/
protoc --cpp_out=src/ --python_out=src/ --proto_path=src/ src/ptc.proto
# now, ptc.pb.h / ptc.pb.cc and ptc_pb2.py are generated in src/

echo "--- Step 2: Compiling ptc_server ---"
# -Isrc allows the compiler to find "ptc.h" and "ptc.pb.h"
g++ -std=c++11 -Isrc -I./include  -o ptc_server \
    src/ptc_server.cxx \
    src/ptc.cc \
    src/i2c.cc \
    src/log.cc \
    src/ptc.pb.cc \
    -L/usr/local/lib \
    -lzmq -lprotobuf -lpthread

echo "--- Step 3: Compiling peek utility ---"
g++ -std=c++11 -Isrc -I./include  -o peek \
    src/ptc.pb.cc \
    src/peek.cc \
    src/ptc.cc \
    src/i2c.cc \
    src/log.cc \
    -L/usr/local/lib \
    -lzmq -lprotobuf -lpthread

echo "--- Step 4: Deployment ---"
# This makes the commands available globally as 'peek' and 'ptc_server'
INSTALL_DIR=/bin
sudo mkdir -p $INSTALL_DIR
sudo cp ptc_server $INSTALL_DIR/
sudo cp peek $INSTALL_DIR/
sudo chmod +x $INSTALL_DIR/ptc_server $INSTALL_DIR/peek

echo "--- Step 5: Compiling i2c_test ---"
g++ -std=c++11 -Isrc -o i2c_test \
    src/i2c_test.cc \
    src/ptc.cc \
    src/i2c.cc \
    src/log.cc \
    -L/usr/local/lib \
    -lzmq -lprotobuf -lpthread

echo "Build Complete. Binaries installed to /bin/"
