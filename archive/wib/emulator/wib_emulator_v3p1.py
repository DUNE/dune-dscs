import zmq
import wib_pb2
from datetime import datetime
from google.protobuf.any_pb2 import Any
from google.protobuf.internal.decoder import _DecodeVarint
import random

VarGlobal = False
addressGlobal = 0x0000
memory = {
    0x0000: 123,
    0x0004: 456,
}
POWER_CTRL_ADDR = 0xDEAD   # or something meaningful

def handle_peek(addr):
    return memory.get(addr, 0)

def handle_poke(addr, value):
    memory[addr] = value

def fill_repeated(field, value_list):
    field.clear()  # remove any previous values
    field.extend(value_list)

def assign_field(field, value, count=1):
    """Handles both repeated and scalar protobuf fields."""
    if hasattr(field, "extend"):
        field.extend([value] * count)
    else:
         # Directly assign if scalar
        return value

def handle_peek_raw(self, peek):
    reply = wib_pb2.RegValue()
    reply.addr = 1234
    print("Dentro de handle_peek_raw reply.addr =",reply.addr)
    return reply.SerializeToString()


def handle_peek_any(self, msg_any):
    peek = wib_pb2.Peek()
    msg_any.Unpack(peek)

    reply = wib_pb2.RegValue()
    reply.addr = 1234

    print("Dentro de handle_peek_any reply.addr =",reply.addr)
    reply_any = Any()
    reply_any.Pack(reply)

    return reply_any.SerializeToString()

def extract_any_from_frame(raw):
    # First byte is the field tag (usually 0x0A)
    pos = 1

    # Decode length varint
    msg_len, new_pos = _DecodeVarint(raw, pos)
    pos = new_pos

    # Extract the real Any message
    return raw[pos:pos + msg_len]

def variation(isstable,stdev):
    if isstable:
        return 0
    rdn = random.gauss(0,stdev)
    if abs(rdn) > stdev:
      return rdn/10
    else:
      return 0

class WIBEmulator:
    def __init__(self):
        self.powered = True
        self.booting = False
        self.boot_start = 0
        
        # If you already have PTC state, integrate here
        self.ptc_status = "ON"   # or whatever structure you use
        self.ADDRESSGLOVAL = 0x0000
        pass

    def update_state(self):
        # Optional periodic state update
        pass

    def power_cycle(self):
        print("[WIB] Power cycling...")
    
        self.powered = False
        self.booting = True
        self.boot_start = time.time()
    
        # Update PTC / status
        self.ptc_status = "OFF"

    # Reset internal state if needed
    # e.g. self.reset_registers()    
    
    #def handle_request(self, raw):
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

#      try:
#        payload = extract_any_from_frame(raw)
#      except Exception as e:
#        print("Frame decode failed:", e)
#        return b''
#      print ("payload", payload)
#      msg_any = Any()
#      try:
#        msg_any.ParseFromString(payload)
#      except Exception as e:
#        print("Failed parsing Any:", e)
#        return b''
#
#      # Normalize type_url
#      type_url = msg_any.type_url.strip().strip('"').strip("'").lstrip('$')
#      print("Received Any:", type_url)
#
  
      if msg_any.type_url.endswith("wib.Peek"):

      # -------- Read request --------
          req = wib_pb2.Peek()
          try:
              msg_any.Unpack(req)
              print(f"REQ addr: {req.addr}")
          except Exception:
              print("[!] No payload in request")
      
          # -------- Build reply --------
          reply = wib_pb2.Peek()
          reply.addr = handle_peek(self.ADDRESSGLOVAL)
      
          print(f"REPLY addr: {reply.addr}")
      
          # -------- Send reply --------
          resp_any = Any()
          resp_any.Pack(reply)
      
          return resp_any.SerializeToString()
      
      elif msg_any.type_url.endswith("wib.Poke"):
      # -------- Read request --------
          req = wib_pb2.Poke()
          msg_any.Unpack(req)

         
          print(f"REQ addr: {req.addr}, value: {req.value}")
          print ("Antes del apagado")
          if req.addr == POWER_CTRL_ADDR:
              if req.value == 1:
                  self.power_cycle()
                  print("[WIB] Power cycle triggered via POKE")
          # Apply write

          handle_poke(req.addr, req.value)

          # Build proper reply
          reply = wib_pb2.RegValue()
          reply.addr = req.addr
          #print ("Este es el adrees =", reply)
#          addressGlobal = reply.addr
          self.ADDRESSGLOVAL = req.addr
          reply.value = req.value

          reply_any = Any()
          reply_any.Pack(reply)

          socket.send(reply_any.SerializeToString())
          reply = wib_pb2.Poke()
          handle_poke(reply.addr, reply.value)
      
          print(f"REPLY addr: {reply.addr}")

      elif msg_any.type_url.endswith("wib.PowerWIB"):
       
          req = wib_pb2.PowerWIB()
          msg_any.Unpack(req)
       
          print("Power command received:")
          print(req)
       
          # Apply power state internally
          state["femb"] = [req.femb0, req.femb1, req.femb2, req.femb3]
          state["cold"] = req.cold
          state["stage"] = req.stage
       
          # Build reply
          reply = wib_pb2.Status()
          reply.success = True   # or your fields
       
          reply_any = Any()
          reply_any.Pack(reply)
       
          socket.send(reply_any.SerializeToString())      
          # -------- Send reply --------
#          resp_any = Any()
#          resp_any.Pack(reply)
      
#          return resp_any.SerializeToString()

  
      elif msg_any.type_url.endswith("wib.GetTimestamp"):
          reply = wib_pb2.GetTimestamp.Timestamp()
          reply.timestamp = int(datetime.utcnow().timestamp())
          reply.day = datetime.utcnow().day
          reply.month = datetime.utcnow().month
          reply.year = datetime.utcnow().year
          reply.hour = datetime.utcnow().hour
          reply.min = datetime.utcnow().minute
          reply.sec = datetime.utcnow().second

          print("[OK] Sent timestamp")
          return reply.SerializeToString()

      elif msg_any.type_url.endswith("wib.GetTimingStatus"):
          reply = wib_pb2.GetTimingStatus.TimingStatus()
          #SI5344 status register values
          reply.lol_val = 1
          reply.lol_flg_val = 2
          reply.los_val = 3
          reply.los_flg_val = 4
          #Firmware timing endpoint status register
          reply.ept_status = 5
          print("[OK] Timing Status")
          return reply.SerializeToString()

  
      elif msg_any.type_url.endswith("wib.GetSWVersion"):
          reply = wib_pb2.GetSWVersion.Version()
          reply.version = "v1.0.0-emulated"
          print("[OK] Sent software version")
          return reply.SerializeToString()

      elif msg_any.type_url.endswith("wib.GetSensors"):
            reply = wib_pb2.GetSensors.Sensors()
            # Voltages 
            reply.ltc2990_4c_voltages.append(1.2+variation(VarGlobal,0.5))# 4 sensorsv0
            reply.ltc2990_4c_voltages.append(1.2+variation(VarGlobal,0.5))
            reply.ltc2990_4c_voltages.append(3.3+variation(VarGlobal,0.5))
            reply.ltc2990_4c_voltages.append(3.3+variation(VarGlobal,0.5))
            reply.ltc2990_4e_voltages.append(0.9+variation(VarGlobal,0.5))# 4 sensors
            reply.ltc2990_4e_voltages.append(0.9+variation(VarGlobal,0.5))
            reply.ltc2990_4e_voltages.append(1.2+variation(VarGlobal,0.5))
            reply.ltc2990_4e_voltages.append(0.6+variation(VarGlobal,0.5))
            reply.ltc2991_48_voltages.append(0.85+variation(VarGlobal,0.5))#8 sensors
            reply.ltc2991_48_voltages.append(0.85+variation(VarGlobal,0.5))
            reply.ltc2991_48_voltages.append(5.0+variation(VarGlobal,0.5))
            reply.ltc2991_48_voltages.append(5.0+variation(VarGlobal,0.5))
            reply.ltc2991_48_voltages.append(2.5+variation(VarGlobal,0.5))
            reply.ltc2991_48_voltages.append(2.5+variation(VarGlobal,0.5))
            reply.ltc2991_48_voltages.append(1.8+variation(VarGlobal,0.5))
            reply.ltc2991_48_voltages.append(1.8+variation(VarGlobal,0.5))
            reply.femb0_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) #8 sensors (nominal 4V)
            reply.femb0_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb0_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) # (nominal 4)
            reply.femb0_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) 
            reply.femb0_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) # (nominal 4)
            reply.femb0_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb0_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) 
            reply.femb0_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) 
            reply.femb1_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) #8 sensors (nominal 4V)
            reply.femb1_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb1_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) # (nominal 4)
            reply.femb1_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb1_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) # (nominal 4)
            reply.femb1_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb1_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) 
            reply.femb1_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) 
            reply.femb2_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) #8 sensors (nominal 4V)
            reply.femb2_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb2_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) # (nominal 4)
            reply.femb2_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb2_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) # (nominal 4)
            reply.femb2_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb2_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) 
            reply.femb2_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) 
            reply.femb3_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) #8 sensors (nominal 4V)
            reply.femb3_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb3_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) # (nominal 4)
            reply.femb3_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb3_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) # (nominal 4)
            reply.femb3_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5))
            reply.femb3_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) 
            reply.femb3_dc2dc_ltc2991_voltages.append(4+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a0_ltc2991_voltages.append(8.0+variation(VarGlobal,0.5)) # 8 sensors
            reply.femb_ldo_a0_ltc2991_voltages.append(8.1+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a0_ltc2991_voltages.append(8.2+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a0_ltc2991_voltages.append(8.3+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a0_ltc2991_voltages.append(8.4+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a0_ltc2991_voltages.append(8.5+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a0_ltc2991_voltages.append(8.6+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a0_ltc2991_voltages.append(8.7+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a1_ltc2991_voltages.append(9.0+variation(VarGlobal,0.5)) # 8 sensors
            reply.femb_ldo_a1_ltc2991_voltages.append(9.1+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a1_ltc2991_voltages.append(9.2+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a1_ltc2991_voltages.append(9.3+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a1_ltc2991_voltages.append(9.4+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a1_ltc2991_voltages.append(9.5+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a1_ltc2991_voltages.append(9.6+variation(VarGlobal,0.5)) 
            reply.femb_ldo_a1_ltc2991_voltages.append(9.7+variation(VarGlobal,0.5)) 
            reply.femb_bias_ltc2991_voltages.append(5.0+variation(VarGlobal,0.5)) #8 sensors
            reply.femb_bias_ltc2991_voltages.append(reply.femb_bias_ltc2991_voltages[0]-(variation(VarGlobal,0.5))) 
            reply.femb_bias_ltc2991_voltages.append(5.0+variation(VarGlobal,0.5)) 
            reply.femb_bias_ltc2991_voltages.append(reply.femb_bias_ltc2991_voltages[2]-(variation(VarGlobal,0.5))) 
            reply.femb_bias_ltc2991_voltages.append(5.0+variation(VarGlobal,0.5)) 
            reply.femb_bias_ltc2991_voltages.append(reply.femb_bias_ltc2991_voltages[4]-(variation(VarGlobal,0.5))) 
            reply.femb_bias_ltc2991_voltages.append(5.0+variation(VarGlobal,0.5)) 
            reply.femb_bias_ltc2991_voltages.append(reply.femb_bias_ltc2991_voltages[6]-(variation(VarGlobal,0.5))) 
            # 0x15 LTC2499 temperature sensor inputs from LTM4644 for FEMB 0 - 3 and WIB 1 - 3
            reply.ltc2499_15_temps.append(5.0+variation(VarGlobal,0.5)) # 7 sensors
            reply.ltc2499_15_temps.append(5.1+variation(VarGlobal,0.5)) 
            reply.ltc2499_15_temps.append(5.2+variation(VarGlobal,0.5)) 
            reply.ltc2499_15_temps.append(5.3+variation(VarGlobal,0.5)) 
            reply.ltc2499_15_temps.append(5.4+variation(VarGlobal,0.5)) 
            reply.ltc2499_15_temps.append(5.5+variation(VarGlobal,0.5)) 
            reply.ltc2499_15_temps.append(5.6+variation(VarGlobal,0.5)) 
            print (reply.femb0_dc2dc_ltc2991_voltages)
            # Onboard temperature sensors
            reply.ad7414_49_temp = 22+variation(VarGlobal,0.5)
            reply.ad7414_4d_temp = 23+variation(VarGlobal,0.5)
            reply.ad7414_4a_temp = 24+variation(VarGlobal,0.5)
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





