import struct
import serial
import sys
import re
import functools

class ProtracClient(object):
    
    def __init_(self,device,baud_rate,io_loop,callback=None):
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
            self.buffer = self.buffer+self.serial.read(1).encode('hex')
            match = self.packet_regex.search(self.buffer)
            if match and match.groups():
                groups = match.groups()
                if (ord(groups[1]) - 4) == len(groups[4]) + len(groups[5]) + len(groups[6]):
                    #self.packet_regex.sub('',self.buffer)#remove it from the buffer
                    #the above wont work if we started halfway through packet, that artifact would last
                    #for the lifetime of the program
                    self.buffer = self.buffer[match.end():]
                    callback = functools.partial(self.callback, match.groups()[4])
                    self.io_loop.add_callback(callback)
        except:
            print sys.exc_info()
            
            
class ProtracPacket(object):
    
    def __init__(self):
        self.start_block
        
        
    def unpack(self,hex_string):
        struct.unpack('',hex_string)