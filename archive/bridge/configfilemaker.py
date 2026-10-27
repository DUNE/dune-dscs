import argparse


parser = argparse.ArgumentParser( description = 'Script used to create multiple emulators with different host' )
parser.add_argument('--n', type = int, required = True, help = 'Number of copies')
parser.add_argument('--port_start', type = int, required = True, help = 'first host number')

args = parser.parse_args()

n_wibs = args.n

ports = [args.port_start + i for i in range(n_wibs)]

template = """\
  - tpc: 0
    wib: {i}
    host: localhost
    port: {port}"""

with open("wibs.yaml", "w") as file:  
    file.write('wibs:\n')
    for i, port in enumerate(ports, start=1):
        file.write(f"{template.format(i=i, port=port)}\n")
 
