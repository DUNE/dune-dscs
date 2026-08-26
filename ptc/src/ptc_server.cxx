// assuming ZeroMQ and Protobuf libraries are available
#include <zmq.hpp>
#include <string>
#include <iostream>
#include "ptc.pb.h"
#include "ptc.h"
#include "log.h"

//main server loop (while): receive command, dispatch to PTC, send back response
int main(int argc, char **argv) {

    // Set output to line buffering for consistent logging
    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IOLBF, 0);

    // Initialize the PTC hardware interface
    PTC ptc; 
    
    // Setup ZeroMQ context and socket
    // use port 7820 (PTC on phone keypad haha) as a placeholder; ensure this matches your client configuration
    zmq::context_t context;
    zmq::socket_t socket(context, ZMQ_REP);
    socket.bind("tcp://*:7820");

    glog.log("PTC Server: Started and listening on port 7820\n");

    // Main server loop
    // Keeps listening for incoming commands, processes them, and sends back responses
    while (true) {

        // Receive a command from the client
        zmq::message_t request;
        
        // Creates a new message object when there's a new message to receive
        auto res = socket.recv(request, zmq::recv_flags::none);

        // if res is created successfully, then we have a new command to process; otherwise, we can just continue to the next loop iteration to wait for the next command
        if (!res) continue;

        // Parse the received command using Protobuf
        ptc::Command command;

	glog.log("PTC Server: Received command type_url = %s\n",command.cmd().type_url().c_str());

        if (!command.ParseFromArray(request.data(), request.size())) {
            glog.log("PTC Server: Failed to parse incoming command\n");
            continue;
        }

        // create a string to hold the serialized reply message
        std::string reply_str;

        // --- Dispatch Logic (Symmetric to WIB Server) ---
        // Handle Peek : read a 32-bit value from the specified address and return it to the client
        if (command.cmd().Is<ptc::Peek>()) {
            ptc::Peek peek_msg;
            command.cmd().UnpackTo(&peek_msg);
            
            // peek() will return 0xFFFFFFFF if the address is invalid or if there's an error; otherwise, it will return the value at the specified address
            uint32_t val = ptc.peek(peek_msg.addr());
            
            // Log the peek operation and its result 
            ptc::RegValue rep;
            rep.set_addr(peek_msg.addr());
            rep.set_value(val);
            rep.SerializeToString(&reply_str);
        } 

        // Handle Poke : write a 32-bit value to the specified address, then read back the value to confirm the poke, and return the read-back value to the client
        else if (command.cmd().Is<ptc::Poke>()) {
            ptc::Poke poke_msg;
            command.cmd().UnpackTo(&poke_msg);
            
            // poke() return type is void, so we don't have a direct way to know if the poke was successful or not; we can only rely on the read-back value to confirm if the poke was successful
            ptc.poke(poke_msg.addr(), poke_msg.value());

            //read back the value to confirm the poke
            uint32_t rb = ptc.peek(poke_msg.addr());
            
            if (rb != poke_msg.value()) {
                glog.log("POKE readback mismatch: wrote 0x%08x, read 0x%08x", poke_msg.value(), rb);
            }

            ptc::RegValue rep;
            rep.set_addr(poke_msg.addr());
            rep.set_value(rb);
            rep.SerializeToString(&reply_str);
        }

        // handle PING : check if the PTC hardware is responsive and return the status to the client by reading the register @ 0x800201FC
        else if (command.cmd().Is<ptc::Ping>()) {
            bool alive = ptc.ping();
            ptc::Status status;
            status.set_success(alive);
            status.SerializeToString(&reply_str);
        }


        //else if (command.cmd().Is<ptc::ReadTemp>()) {
          //  ptc::ReadTemp req;
            //command.cmd().UnpackTo(&req);

            //double temp = ptc.read_temperature(req.addr());

            //ptc::TempValue rep;
            //rep.set_addr(req.addr());
            //rep.set_value(temp);
        //}

	        // handle temperature read
        else if (command.cmd().Is<ptc::ReadTemperature>()) {
            ptc::ReadTemperature temp_msg;
            command.cmd().UnpackTo(&temp_msg);

            double temp_c = ptc.read_tmp117_temp_c(
                static_cast<uint8_t>(temp_msg.mux_channel()),
                static_cast<uint8_t>(temp_msg.addr())
            );

	    glog.log("PTC Server: ReadTemperature value = %f\n", temp_c);

            ptc::DoubleValue rep;
            rep.set_value(temp_c);
            rep.SerializeToString(&reply_str);
        }

        // handle voltage read
        else if (command.cmd().Is<ptc::ReadVoltage>()) {
            ptc::ReadVoltage volt_msg;
            command.cmd().UnpackTo(&volt_msg);

            double volts = ptc.read_ltc2945_voltage_v(
                static_cast<uint8_t>(volt_msg.mux_channel()),
                static_cast<uint8_t>(volt_msg.addr())
            );

	    glog.log("PTC Server: ReadVoltage value = %f\n", volts);


            ptc::DoubleValue rep;
            rep.set_value(volts);
            rep.SerializeToString(&reply_str);
        }

        // handle current read
        else if (command.cmd().Is<ptc::ReadCurrent>()) {
            ptc::ReadCurrent curr_msg;
            command.cmd().UnpackTo(&curr_msg);

            double amps = ptc.read_ltc2945_current_a(
                static_cast<uint8_t>(curr_msg.mux_channel()),
                static_cast<uint8_t>(curr_msg.addr()),
                curr_msg.shunt_ohm()
            );

	    glog.log("PTC Server: ReadCurrent value = %f\n", amps);


            ptc::DoubleValue rep;
            rep.set_value(amps);
            rep.SerializeToString(&reply_str);
        }

	else if (command.cmd().Is<ptc::PowerWIB>()) {
    		ptc::PowerWIB req;
    		command.cmd().UnpackTo(&req);

    		ptc.power_wib(
        	static_cast<int>(req.slot()),
        		req.on()
    		);

    		ptc::Status rep;
    		rep.set_success(true);
    		rep.SerializeToString(&reply_str);
	}

	else if (command.cmd().Is<ptc::ReadWIBPowerRequest>()) {

 		ptc::ReadWIBPowerRequest power_msg;
    		command.cmd().UnpackTo(&power_msg);

    		uint32_t wib = power_msg.wib();

    		uint8_t addr = 0x67 + wib;

   	 	double volts = ptc.read_ltc2945_voltage_v(
        	3,
        	addr
    		);

    		double amps = ptc.read_ltc2945_current_a(
        	3,
        	addr,
        	0.005
    		);

    		ptc::ReadWIBPowerReply rep;
    		rep.set_voltage(volts);
    		rep.set_current(amps);

    		rep.SerializeToString(&reply_str);
		printf("Reading mux=%u addr=0x%02x\n", wib, addr);

	}	

	else if (command.cmd().Is<ptc::PowerAllWIBs>()) {

    		ptc::PowerAllWIBs req;
    		command.cmd().UnpackTo(&req);

    		ptc.power_all_wibs(req.on());

    		ptc::Status rep;
    		rep.set_success(true);
    		rep.SerializeToString(&reply_str);
	}

        else {
	glog.log("PTC Server: Received unknown command type: %s\n",command.cmd().type_url().c_str());
	ptc::Status status;    
	status.set_success(false);
            status.SerializeToString(&reply_str);
        }

        // Send the serialized reply back to client
        zmq::message_t reply(reply_str.size());
        memcpy(reply.data(), reply_str.data(), reply_str.size());
        socket.send(reply, zmq::send_flags::none);
    }

    return 0;
}
