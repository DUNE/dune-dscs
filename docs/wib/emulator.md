# Python source code for the WIB emulator

Data are communicated with Protobuf buffers over ZeroMQ

Emulators for WIB


To run a singular wib emulator, just run a a python script the emulator chosen. For example:
python wib_emulator_v3p1.py

By the fault all the basis emulators are comunicated by the port 5555.

Multiple wibs run.

To run multple wibs at same time, using quasar or python bridge(some special conditions for quasar bridge), it is necesary to produce the emulator copies first with their respective ports. To do that, you can run produce_wibs.sh script specifying the emulator that you want to copy, the number of copies and the port start number. For example:

source produce_wibs.sh wib_emulator_v3p1.sh 10 21000

This will produce ten wibs emulators with their respective port number starting on 21000.

Special conditions for quasar bridge

To have the connection between the bridge and the wib is necesary to produce the config file in quasar. The script produce_wibs.sh produce this config file foryou, you only need to specify the location in quasar build area, for more specific instructions look at comments in the "produce_wibs.sh" script. 

For quasar bridge we found that it crash for more that 160 wibs wib emulators, therefore we recommend to work with bellow of 140 wibs per quasar server. If you want to use multiple quasar servers you can use the script "produce_wibs_multiple.sh". This script produce the config files for the multple quasar servers giving an specific number of wibs per quasar server. It is useful only for the quasar bridge. 

Run multple wibs

To run multiple wibs as background process you can use the script "run_wibs_list.sh". The number of wibs and the port number must be specified. For exaple:

source run_wibs_list.sh 10 21000

To stop the wibs, you have to kill the process using

kill -9 \<process number\>
