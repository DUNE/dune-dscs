# Tutorial: How to Build a Basic Emulator & Python Bridge for DUNE Slow Controls

Welcome to this hands-on tutorial! Here, we will show you how to build a hardware **Emulator** (a basic WIB simulator based on ZeroMQ) and a **Communication Bridge** in Python that communicates with an OPC-UA monitoring program.

---

## Prerequisites

Before getting started, make sure you have **Ignition** or **Visual Studio Code** installed with the **OPC-UA Browser** extension.

### Required Python Libraries

> [!WARNING]
> **Important Protobuf Version:** Please ensure you use `protobuf` version **3.20 or lower** (version `3.19.6` is recommended to avoid compatibility issues).

Upgrade `pip` and install the required dependencies using the commands below:

```bash
# Upgrade pip
pip install --upgrade pip

# Install specific Protobuf version
pip install protobuf==3.19.6
sudo apt  install protobuf-compiler

# Install OPC-UA libraries
pip3 install asyncua
pip install opcua

pip install PyYAML

```
---

## Setup & Execution

> **Tip:** We recommend opening **two terminal windows**: one to run the WIB Emulator and another to run the Bridge.

### Terminal 1: Run the WIB Emulator

1. Open a terminal and clone the repository:
   ```bash
   git clone https://github.com/DUNE/dune-dscs.git
   cd dune-dscs/Tutorials/workshop2026/
   
2. Start the zmq emulator:
   ```bash
   python zmq_emulator.py

### Terminal 2: Run the Communication Bridge

1. Open a second terminal and go to the workshop folder:
   ```bash
   cd dune-dscs/Tutorials/workshop2026/

3. Start the Python bridge:
   ```bash
   python ignition_pybridge.py
   ```

    
