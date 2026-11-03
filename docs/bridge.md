# Python source code for the WIB OPC/UA bridge

Don't forget to make the set up previously to run the bridge and the emulator. If you are int bridge directory do:

cd ..; source setup.sh; cd -

To run the bridge is necesary to setup the config files for the devises.

For the case of the wib emulators, it is necesary to run the python script "wib_configfilemaker.py" as follows:

python configfilemaker.py --n=\<number of wibs\> --port_start=\<fisrt port number\>

for example

python configfilemaker.py --n=1 --port_start=5555

It will produce a wib.yaml that contains the tpc, wib number, host and port number for each wib.
