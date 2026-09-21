# Tutorial: How to Build a Basic Emulator & Python Bridge for DUNE Slow Controls

Welcome to this hands-on tutorial! Here, we will show you how to build a hardware **Emulator** (a basic WIB simulator based on ZeroMQ) and a **Communication Bridge** in Python that communicates with an OPC-UA monitoring program.

---

## Prerequisites

Before starting, make sure you have the following installed:
* **Visual Studio Code** with the **OPC-UA Browser** extension.
* **Python 3.x**
* Required Python libraries:
  * `pyzmq`
  * `asyncua` (or `opcua`)
  * *(add other libraries here)*

---

## Setup & Execution

> **Tip:** We recommend opening **two terminal windows**: one to run the WIB Emulator and another to run the Bridge.

### Terminal 1: Run the WIB Emulator

1. Open a terminal and clone the repository:
   ```bash
   git clone [https://github.com/DUNE/dune-dscs.git](https://github.com/DUNE/dune-dscs.git)
   cd dune-dscs/wib/wib-emulator

2. Run the environment setup script:
   ```bash
   source setup.sh
   
3. Start the WIB emulator:
   ```bash
   python wib_emulator_v3p1.py

### Terminal 2: Run the Communication Bridge

1. Open a second terminal and navigate to the bridge folder:
   ```bash
   cd dune-dscs/wib/bridge

2. Run the environment setup script:
   ```bash
   source setup.sh

3. Start the Python bridge:
   ```bash
   python ignition_pybridge.py


    
