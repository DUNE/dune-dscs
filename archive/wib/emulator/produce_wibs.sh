# This is the main script to priduce mutiple wibs that are connected to only one quasar server.
#You only need to give the name of the wib emulator that you want to copy, the number of emulators
# and the number of the first port that the wib will use. This can be used for the quasar and the
#python bridge, If you want to use quasar bridge and produce the config files you only need to 
#uncomment the line "python configfilemaker.py --n=$n --host_start=$host_start" and 
#"mv config.xml /home/dunedcs/wib_opcua_cc_threadlimit/multirun/wibopcua1/build/bin". Don't 
#forget to specify the location for the config file in quasar.
#TODO: Get the quasar bridge location from the setup.

infile=$1
n=$2
port_start=$3
python emulatorCopier.py --infile=$infile --n=$n --host_start=$port_start
#python configfilemaker.py --n=$n --port_start=$port_start

#mv config.xml /home/dunedcs/wib_opcua_cc_threadlimit/multirun/wibopcua1/build/bin

