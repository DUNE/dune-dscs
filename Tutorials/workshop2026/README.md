# Tutorial: How to Build a Basic Emulator & Python Bridge for DUNE Slow Controls

Welcome to this hands-on tutorial! Here, we will show you how to build a hardware **Emulator** (a basic WIB simulator based on ZeroMQ) and a **Communication Bridge** in Python that communicates with an OPC-UA monitoring program.

---

## Prerequisites

Before getting started, make sure you have **Ignition** or **Visual Studio Code** installed with the **OPC-UA Browser** extension.

### Required Python Libraries

> [!WARNING]
> **Important Protobuf Version:** `zmq_em_pb2.py` needs `protobuf` **7.36.1 or newer**; older versions such as `3.19.6` fail to import it.

Upgrade `pip` and install the required dependencies using the commands below:

```bash
# Upgrade pip
pip install --upgrade pip

# Install Protobuf (7.36.1 or newer)
pip install "protobuf>=7.36.1"

# Install ZeroMQ bindings
pip install pyzmq

# Install OPC-UA libraries
pip3 install asyncua
pip install opcua

pip install PyYAML

```

### Optional: Regenerate the Protobuf Code

Only needed if you change `zmq_em.proto` or must use an older `protobuf`. Run from the workshop folder:

```bash
# Linux (Debian/Ubuntu)
sudo apt install protobuf-compiler

# macOS
brew install protobuf

# Regenerate zmq_em_pb2.py
protoc --python_out=. zmq_em.proto
```

---

## Setup & Execution

> **Tip:** We recommend opening **two terminal windows**: one to run the WIB Emulator and another to run the Bridge.

### Terminal 1: Run the WIB Emulator

1. Open a terminal and clone the repository:
   ```bash
   git clone https://github.com/DUNE/dune-dscs.git
   cd dune-dscs/Tutorials/workshop2026/
   ```

2. Start the zmq emulator:
   ```bash
   python zmq_emulator.py
   ```

### Terminal 2: Run the Communication Bridge

1. Open a second terminal and go to the workshop folder:
   ```bash
   cd dune-dscs/Tutorials/workshop2026/
   ```

2. Start the Python bridge:
   ```bash
   python ignition_pybridge.py
   ```

---

## Connecting Ignition (8.3) to the Bridge

1. In the Ignition Gateway web interface, create a new **OPC UA** connection (for example named `ZMQ Bridge`).
2. Set the **Endpoint URL** to:
   ```
   opc.tcp://127.0.0.1:4840/freeopcua/server/
   ```
3. Set **Security Policy** to `None`, **Security Mode** to `None`, and use anonymous authentication (no username or password).
4. Save the connection. Its status should change to `Connected`, and the `ZMQD1` object with the sensor nodes appears in the OPC browser.

> [!NOTE]
> **Use `127.0.0.1`, not `localhost`;** `localhost` fails with `Bad_ConfigurationError: no matching endpoints found`. If Ignition runs on another machine, use the bridge machine's IP address.
