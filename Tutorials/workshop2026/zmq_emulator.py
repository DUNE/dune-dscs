import zmq 
import zmq_em_pb2 # Loads the Python message definitions generated from the protobuf file
#message GetSensors {
#    double Temp1 = 1;
#    repeated double vol1 = 2;
#}
from datetime import datetime 
from google.protobuf.any_pb2 import Any
from google.protobuf.internal.decoder import _DecodeVarint
import random

import os


class WIBEmulator: #Class that knows how to interpret a request and construct a response.
    def __init__(self):
        self.ADDRESSGLOVAL = 0x0000
        pass
    
    def handle_request(self, raw_msg: bytes): #receiving a message for processing 
    #Incoming bytes → interpret request → create response → return response bytes
      try:
          raw_str = raw_msg.decode("utf-8").strip().strip('"')
      except Exception:
          raw_str = ""
      msg_any = Any() # Reading the protobuf envelope
      try:
          msg_any.ParseFromString(raw_msg)
      except Exception as e:
          print(f"[!] Error parsing protobuf Any: {e}")
          return None

#      print(f"[>] Got type_url = {msg_any.type_url}")

      if msg_any.type_url.endswith("zmq_em.GetSensors"): # checking what was requested
            reply = zmq_em_pb2.GetSensors() # create the response 
            # Add your sensors here
            #reply.Temp1 = 24
            #reply.vol1.append(12)
            #reply.vol1.append(22)
            # Simulate changing sensor readings
            reply.Temp1 = 24 + random.gauss(0, 0.5)
            reply.vol1.append(12 + random.gauss(0, 0.1))
            reply.vol1.append(22 + random.gauss(0, 0.1))

            print ("Temo1 = ", reply.Temp1)
            print ("vol1[0] = ", reply.vol1[0])
            print ("vol1[1] = ", reply.vol1[1])

            print("[OK] Sent sensor readings")
            return reply.SerializeToString() #return the response bytes 
  
      else:
          print("Unknown type:", msg_any.type_url)
          return b''

    # ---------- Unknown ----------
      print("Unknown message format")
      return None

def main(): # setting up network listener
    context = zmq.Context() # manages communication resources

    #Creates a reply socket. It pairs with the bridge’s request socket
        #Bridge:   REQ — sends a request, waits for a reply # Receive → Send → Receive → Send
        #Emulator: REP — receives a request, sends a reply

    socket = context.socket(zmq.REP)

    #Emulator binds: provides the listening endpoint.
    #Bridge connects: chooses the emulator’s address.
    #socket.bind("tcp://*:5555")

    #print("ZMQ Emulator running at tcp://*:5555")
    port = int(os.environ.get("EMULATOR_PORT", "5555"))
    socket.bind(f"tcp://*:{port}")
    print(f"ZMQ Emulator running on port {port}", flush=True)

    #Create message handler
    wib = WIBEmulator()

    while True:
        try:
            #Waits for an incoming request.
            raw = socket.recv()
            
            l = len(raw)
           # calis = raw[28:32]
           # raw = raw[:32]
           
            #Passes the received bytes into the handler
            reply = wib.handle_request(raw)
            if reply:
                socket.send(reply)
            else:
                print ("Wrong message, the reply is empty")
                socket.send(b"")
        except Exception as e:
            print(f"[!] Runtime error: {e}")
            socket.send(b"")

if __name__ == "__main__":
    main()



