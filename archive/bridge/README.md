# Shared OPC UA bridge

The bridge polls WIB version, timing status, sensors and firmware timestamp.
It sends no register writes, configuration, reset or power commands. OPC-UA
clients can read the published values; they cannot change them. Removed debug
`peek` nodes are no longer published.

Add A5202 devices to this same server using `fers_devices` in `devices.yaml`.
See the [A5202 setup and node reference](../../docs/fers.md). FERSlib opens one
persistent connection per board; opening it stops acquisition and can write
calibration settings. Use this mode only when the bridge owns the board.

Telemetry requests may still cause internal hardware writes in the target
firmware. For example, the WIB `read_timing_status` implementation pinned by
`sc_emu` [updates a DAQ-header register](https://github.com/DUNE-DAQ/dune-wib-firmware/blob/ee0a4cd528f6e9a2fef90c205088173b149a91f2/sw/src/wib.cc#L937). This bridge's command restriction is
not proof of zero hardware writes. Check the installed firmware before hardware use.

Don't forget to make the set up previously to run the bridge and the emulator. If you are int bridge directory do:

cd ..; source setup.sh; cd -

To run the bridge is necesary to setup the config files for the devises.

For the case of the wib emulators, it is necesary to run the python script "wib_configfilemaker.py" as follows:

python configfilemaker.py --n=\<number of wibs\> --port_start=\<fisrt port number\>

for example

python configfilemaker.py --n=1 --port_start=5555

It will produce a wib.yaml that contains the tpc, wib number, host and port number for each wib.
