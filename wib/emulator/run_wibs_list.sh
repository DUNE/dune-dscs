#This script run all the wibs that has been produced as a background process.
n=$1
host_start=$2
stops=$host_start+$n
for ((i=$host_start; i<$stops; i++)); do
#  xterm -title "host $i" -hold -e "bash -c 'python wib_emulator_v1_host_$i.py'" & #produce a terminal per wib
  nohup python wib_emulator_v3p1_host_$i.py > /dev/null 2>&1 & #run a wib as background process
done

