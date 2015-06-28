from tornado.tcpclient import TCPClient
import collections

def DmtpClient(TCPClient):
    def __init__(self,url,port):
        
        self.queue = collections.deque()
    

def hex_from_string(str):
    return map(hex, map(ord, str))


def start_block():
    return '\xE0'



def packet_type(packet,packet_type):
    packet = '\xE0'
    packet 
    