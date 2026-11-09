import zmq 
import zmq_em_pb2 
from google.protobuf.any_pb2 import Any
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

      if msg_any.type_url.endswith("zmq_em.GetSensors"):
            reply = zmq_em_pb2.GetSensors()
            # Define the value of your sensors here 
            reply.Temp1 = 24 
            reply.vol1.append(12)
            reply.vol1.append(22)
            
            print ("Temp1 = ", reply.Temp1)
            print ("vol1[0] = ",  reply.vol1[0])
            print ("vol1[1] = ", reply.vol1[1])
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

    print("ZMQ Emulator running at tcp://*:5555")

    wib = WIBEmulator()

    while True:
        try:
            raw = socket.recv()
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



