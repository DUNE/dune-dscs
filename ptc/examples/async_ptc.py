import asyncio
import logging

from asyncua import Server, ua
from asyncua.common.methods import uamethod


@uamethod
def func(parent, value):
    return value * 2


async def main():
    _logger = logging.getLogger(__name__)
    # setup our server
    server = Server()
    await server.init()
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")

    # set up our own namespace, not really necessary but should as spec
    uri = "http://examples.freeopcua.github.io"
    idx = await server.register_namespace(uri)

    # populating our address space
    # server.nodes, contains links to very common nodes like objects and root

    ptcobj = {}
    nptcs = 150
    nwibspercrate = 6

    timingstatus = [0 for i in range(nptcs)]
    tempsensor = [0 for i in range(nptcs)]
    wibenabled = [[0 for j in range(nwibspercrate)] for i in range(nptcs)]
    wibvoltage = [[0 for j in range(nwibspercrate)] for i in range(nptcs)]
    wibcurrent = [[0 for j in range(nwibspercrate)] for i in range(nptcs)]

    for iptc in range(0,nptcs):
        ptcobj[iptc] = await server.nodes.objects.add_object(idx, "WIEC_PTC_"+str(iptc))
        timingstatus[iptc] = await ptcobj[iptc].add_variable(idx, "TimingStatus", 0.0)
        await timingstatus[iptc].set_writable()
        tempsensor[iptc] = await ptcobj[iptc].add_variable(idx, "TemperatureSensor", 0.0)
        await tempsensor[iptc].set_writable()
        for iwib in range(nwibspercrate):
            wibenabled[iptc][iwib] = await ptcobj[iptc].add_variable(idx, "WIBEnabled_"+str(iwib), 0.0)
            await wibenabled[iptc][iwib].set_writable()
            wibvoltage[iptc][iwib] = await ptcobj[iptc].add_variable(idx, "WIBVoltage_"+str(iwib), 0.0)
            await wibvoltage[iptc][iwib].set_writable()
            wibcurrent[iptc][iwib] = await ptcobj[iptc].add_variable(idx, "WIBCurrent_"+str(iwib), 0.0)
            await wibcurrent[iptc][iwib].set_writable()
            
    await server.nodes.objects.add_method(
        ua.NodeId("ServerMethod", idx),
        ua.QualifiedName("ServerMethod", idx),
        func,
        [ua.VariantType.Int64],
        [ua.VariantType.Int64],
    )
    _logger.info("Starting server!")
    
    async with server:
        while True:
            await asyncio.sleep(1)
            for iptc in range(nptcs):
                new_val = await tempsensor[iptc].get_value() + 0.1
                await tempsensor[iptc].write_value(new_val)
                for iwib in range(nwibspercrate):
                   new_val = await wibvoltage[iptc][iwib].get_value() + 0.1
                   await wibvoltage[iptc][iwib].write_value(new_val)
                   new_val = await wibcurrent[iptc][iwib].get_value() + 0.1
                   await wibcurrent[iptc][iwib].write_value(new_val)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main(), debug=True)
