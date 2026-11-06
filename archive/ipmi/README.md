# DUNE slow controls software for devices communicating with ipmi

To run the emulator just run:

python ipmi\_emulator.py

or, you can give the specific host, prot and sensors that will be used. This is one example:
    
python3 ipmi\_emulator.py --host 0.0.0.0 --port 6230 --sensors "Temp1,Fan1,Voltage1"

