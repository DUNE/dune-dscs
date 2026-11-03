#Config file maker used to produce the necesary config file to connect the wibs with the 
#quasar bridge.


import argparse


parser = argparse.ArgumentParser( description = 'Script used to create multiple emulators with different host' )
parser.add_argument('--n', type = int, required = True, help = 'Number of copies')
parser.add_argument('--host_start', type = int, required = True, help = 'first host number')

args = parser.parse_args()

n_wibs = args.n

ports = [args.host_start + i for i in range(n_wibs)]

template = """\
    <WIB zmq_endpoint="tcp://localhost:{port}" name="wib_{i}" poll_period="1">
        <FEMBPower name="power" ldo_a1_setpoint="2.5" ldo_a0_setpoint="2.5"
                   dc2dc_o1_setpoint="4.0" dc2dc_o2_setpoint="4.0"
                   dc2dc_o3_setpoint="4.0" dc2dc_o4_setpoint="4.0"
                   cold="false" femb0_on="false" femb1_on="false"
                   femb2_on="false" femb3_on="false" stage="0"/>
        <Sensors name="sensors"/>
        <TimingEndpoint name="timing"/>
    </WIB>"""

with open("config.xml", "w") as file:  
    file.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    file.write('<configuration xmlns="http://cern.ch/quasar/Configuration" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://cern.ch/quasar/Configuration ../Configuration/Configuration.xsd ">\n')
    for i, port in enumerate(ports, start=1):
        file.write(f"{template.format(i=i, port=port)}\n")
    file.write('</configuration>')
