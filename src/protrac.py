import struct
import serial
import sys
import re
import functools
import time

class ProtracPacket(object):
    
    def __init__(self,rssi,cust_num,tag_num,tag_seq,switch_count,battery,flags,recv_bytes,temperature,timestamp):
        self.rssi = rssi
        self.cust_num = cust_num
        self.tag_num = tag_num
        self.tag_seq = tag_seq
        self.switch_count = switch_count
        self.battery = battery
        self.flags = flags
        self.recv_bytes = recv_bytes
        self.temperature = temperature
        self.timestamp = timestamp
        pass
    
    def decode(self,packet):
        self.rssi = packet[0:1].encode('hex')
        self.cust_num = packet[1:3].encode('hex')
        self.tag_num = packet[3:6].encode('hex')
        self.tag_seq = packet[6:7].encode('hex')
        self.switch_count = packet[7:8].encode('hex')
        self.battery = packet[8:9].encode('hex')
        self.flags = packet[9:10].encode('hex')
        self.recv_bytes = packet[10:11].encode('hex')
        self.temperature = int(packet[11:].encode('hex'),16)*0.2-50

    
class ProtracClient(object):
    
    def __init__(self,device,baud_rate,io_loop,callback=None):
        self.serial = serial.Serial(device,baud_rate)
        self.serial.nonblocking()
        self.buffer = ''
        self.io_loop = io_loop
        #TODO: handle ioloop.ERROR
        self.io_loop.add_handler(self.serial.fileno(),self._on_data,io_loop.READ)
        self.packet_regex = \
            re.compile('(\xaa)([\x04-\xFF]{1})([\x00-\xFF]{1})([\x10-\xFF]{1})([\x00-\xFF]*)([\x00-\xFF]{1})(\x44)')
            
        self.callback = callback
        
        
    
    def _on_data(self,fd,events):
        try:
	    data = self.serial.read(1) 
	    self.buffer = self.buffer+data
	    match = self.packet_regex.search(self.buffer)
            if match and match.groups():
                print 'got a match' 
		groups = match.groups()
                print groups 
		if (ord(groups[1]) - 2) == len(groups[4]) + len(groups[5]) + len(groups[6]):
                    #self.packet_regex.sub('',self.buffer)#remove it from the buffer
                    #the above wont work if we started halfway through packet, that artifact would last
                    #for the lifetime of the program
                    print 'removing from buffer'
  		    print match.end() 
		    self.buffer = self.buffer[match.end():]
                    callback = functools.partial(self.callback, match.groups()[4])
                    self.io_loop.add_callback(callback)
        except:
            print sys.exc_info()
            
        pass            

