import zmq 
import zmq_em_pb2 
from datetime import datetime
from google.protobuf.any_pb2 import Any
from google.protobuf.internal.decoder import _DecodeVarint
import random


class WIBEmulator:
    def __init__(self):
        self.ADDRESSGLOVAL = 0x0000
        pass
    
    def handle_request(self, raw_msg: bytes):

      try:
          raw_str = raw_msg.decode("utf-8").strip().strip('"')
      except Exception:
          raw_str = ""
      msg_any = Any()
      try:
          msg_any.ParseFromString(raw_msg)
      except Exception as e:
          print(f"[!] Error parsing protobuf Any: {e}")
          return None

      print(f"[>] Got type_url = {msg_any.type_url}")

      if msg_any.type_url.endswith("wib.GetSensors"):
            reply = zmq_em_pb2.GetSensors()
            # Voltages 
            reply.Temp1 = 24
            reply.vol1.append(12)
            reply.vol1.append(22)

            print("[OK] Sent sensor readings")
            return reply.SerializeToString()
  
      else:
          print("Unknown type:", msg_any.type_url)
          return b''

    # ---------- Unknown ----------
      print("Unknown message format")
      return None

def main():
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind("tcp://*:5555")

    print("WIB Emulator running at tcp://*:5555")

    wib = WIBEmulator()

    while True:
        try:
            raw = socket.recv()
            print(f"\n[<] Received {len(raw)} bytes")
            print ("Before get handle request")
            
            l = len(raw)
           # calis = raw[28:32]
           # raw = raw[:32]
            print("Printing raw",raw[:l])
            reply = wib.handle_request(raw)
            print ("After get handle request")
            if reply:
                print(f"Sending something {reply}")
                socket.send(reply)
            else:
                print ("Wrong message, the reply is empty")
                socket.send(b"")
        except Exception as e:
            print(f"[!] Runtime error: {e}")
            socket.send(b"")

if __name__ == "__main__":
    main()



