# Tutorial: How to Build a Basic Emulator & Python Bridge for DUNE Slow Controls

Welcome to this hands-on tutorial! Here, we will show you how to build a hardware **Emulator** (a basic WIB simulator based on ZeroMQ) and a **Communication Bridge** in Python that communicates with an OPC-UA monitoring program.

---

## Prerequisites

Before getting started, make sure you have **Ignition** or **Visual Studio Code** installed with the **OPC-UA Browser** extension.

### Required Python Libraries

> [!WARNING]
> **Important Protobuf Version:** The checked-in `zmq_em_pb2.py` was generated with protobuf **7.36.1**, so you need `protobuf` version **7.36.1 or newer**. Older versions (for example `3.19.6`) fail with `ImportError: cannot import name 'runtime_version'`. If you must use an older protobuf, regenerate `zmq_em_pb2.py` with a matching `protoc` (see below).

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

You only need the protobuf compiler (`protoc`) if you change `zmq_em.proto` or use a protobuf version older than 7.36.1. Install it and regenerate `zmq_em_pb2.py` from the workshop folder:

```bash
# Linux (Debian/Ubuntu)
sudo apt install protobuf-compiler

# macOS
brew install protobuf

# Regenerate zmq_em_pb2.py
protoc --python_out=. zmq_em.proto
```

The generated file requires a `protobuf` Python package at least as new as the `protoc` that produced it.

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

The bridge prints `Listening on 0.0.0.0:4840`. `0.0.0.0` is only the address it listens on (all network interfaces); clients must connect to a real address of the machine, such as `127.0.0.1`.

---

## Connecting Ignition to the Bridge

These steps were tested with Ignition 8.3 running on the same machine as the bridge.

1. In the Ignition Gateway web interface, create a new **OPC UA** connection (for example named `ZMQ Bridge`).
2. Set the **Endpoint URL** to:
   ```
   opc.tcp://127.0.0.1:4840/freeopcua/server/
   ```
3. Set **Security Policy** to `None`, **Security Mode** to `None`, and use anonymous authentication (no username or password).
4. Save the connection. Its status should change to `Connected`, and the `ZMQD1` object with the sensor nodes appears in the OPC browser.

> [!NOTE]
> **Use `127.0.0.1`, not `localhost`.** The bridge (python-opcua) advertises its endpoint with the IP address the client connected to, here `opc.tcp://127.0.0.1:4840/freeopcua/server/`. Ignition only accepts an endpoint whose URL matches the one it was given, so a connection to `opc.tcp://localhost:4840` faults with `Bad_ConfigurationError: no matching endpoints found`. If Ignition runs on a different machine, use the IP address of the machine running the bridge instead of `127.0.0.1`.

The bridge offers only security policy `None` with no authentication, which is fine for a local tutorial but not for a production system.
