import zmq
import ptc_pb2 # this gets created by the build.sh script

class PTC:
    # server number and port might have to change
    def __init__(self, server='127.0.0.1', port=7820):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect(f"tcp://{server}:{port}")

    def send_command(self, req, rep):
        cmd = ptc_pb2.Command()
        cmd.cmd.Pack(req)
        self.socket.send(cmd.SerializeToString())
        rep.ParseFromString(self.socket.recv())

    def peek(self, addr):
        req = ptc_pb2.Peek()
        req.addr = addr
        rep = ptc_pb2.RegValue()
        self.send_command(req, rep)
        return rep.value

    def poke(self, addr, value):
        req = ptc_pb2.Poke()
        req.addr = addr
        req.value = value
        rep = ptc_pb2.RegValue()
        self.send_command(req, rep)
        return rep.value
    
    def ping(self):
        req = ptc_pb2.Ping()
        rep = ptc_pb2.Status()
        self.send_command(req, rep)
        return rep.success

    def read_temperature(self, mux_channel, addr):
        req = ptc_pb2.ReadTemperature()
        req.mux_channel = mux_channel
        req.addr = addr
        rep = ptc_pb2.DoubleValue()
        self.send_command(req, rep)
        return rep.value

    def read_voltage(self, mux_channel, addr):
        req = ptc_pb2.ReadVoltage()
        req.mux_channel = mux_channel
        req.addr = addr
        rep = ptc_pb2.DoubleValue()
        self.send_command(req, rep)
        return rep.value

    def read_current(self, mux_channel, addr, shunt_ohm):
        req = ptc_pb2.ReadCurrent()
        req.mux_channel = mux_channel
        req.addr = addr
        req.shunt_ohm = shunt_ohm
        rep = ptc_pb2.DoubleValue()
        self.send_command(req, rep)
        return rep.value

    def power_wib(self, slot, on):

        req = ptc_pb2.PowerWIB()
        req.slot = slot
        req.on = on
        rep = ptc_pb2.Status()
        self.send_command(req, rep)
        return rep.success

    def read_wib_power(self, wib):
        req = ptc_pb2.ReadWIBPowerRequest()
        req.wib = wib

        rep = ptc_pb2.ReadWIBPowerReply()

        self.send_command(req, rep)


        return (
            rep.voltage,
            rep.current
        )

