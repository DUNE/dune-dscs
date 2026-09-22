# Tutorial: How to Build a Basic Emulator & Python Bridge for DUNE Slow Controls

Welcome to this hands-on tutorial! Here, we will show you how to build a hardware **Emulator** (a basic WIB simulator based on ZeroMQ) and a **Communication Bridge** in Python that communicates with an OPC-UA monitoring program.

---

## Prerequisites

Before getting started, make sure you have **Visual Studio Code** installed with the **OPC-UA Browser** extension.

### Required Python Libraries

> [!WARNING]
> **Important Protobuf Version:** Please ensure you use `protobuf` version **3.20 or lower** (version `3.19.6` is recommended to avoid compatibility issues).

Upgrade `pip` and install the required dependencies using the commands below:

```bash
# Upgrade pip
pip install --upgrade pip

# Install specific Protobuf version
pip install protobuf==3.19.6

# Install OPC-UA libraries
pip3 install asyncua
pip install opcua

# Install IPMI library
pip install python-ipmi

# Install SNMP library
pip install pysnmp
```
---

## Setup & Execution

> **Tip:** We recommend opening **two terminal windows**: one to run the WIB Emulator and another to run the Bridge.

### Terminal 1: Run the WIB Emulator

1. Open a terminal and clone the repository:
   ```bash
   git clone [https://github.com/DUNE/dune-dscs.git](https://github.com/DUNE/dune-dscs.git)
   cd dune-dscs/Tutorials/workshop2026/wib-emulator

2. Run the environment setup script:
   ```bash
   source setup.sh
   
3. Start the WIB emulator:
   ```bash
   python wib_emulator_v3p1.py

### Terminal 2: Run the Communication Bridge

1. Open a second terminal and navigate to the bridge folder:
   ```bash
   cd dune-dscs/Tutorials/workshop2026/bridge

2. Run the environment setup script:
   ```bash
   source setup.sh

3. Start the Python bridge:
   ```bash
   python ignition_pybridge.py
   ```

    
