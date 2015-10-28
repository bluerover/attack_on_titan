import tornado
import protrac
import datetime
from tornado import ioloop
import pika
from pika import adapters
from consumer import Consumer,Producer
import json
import time

io_loop = tornado.ioloop.IOLoop.instance()
producer = Producer('amqp://guest:guest@localhost:5672/%2F',io_loop)
def handle_callback_exception(callback):
    self.assertIs(sys.exc_info()[0], ZeroDivisionError)
    self.stop()

io_loop.handle_callback_exception = handle_callback_exception

def on_packet(packet):
    print datetime.datetime.now() 
    print 'rssi:%s custNum:%s tagNum:%s tagSeq:%s switchCount:%s batter:%s flags:%s recv byte:%s temperature:%s '\
    %(packet[0:1].encode('hex'),\
    packet[1:3].encode('hex'),\
    packet[3:6].encode('hex'),\
    packet[6:7].encode('hex'),\
    packet[7:8].encode('hex'),\
    packet[8:9].encode('hex'),\
    packet[9:10].encode('hex'),\
    packet[10:11].encode('hex'),\
    int(packet[11:].encode('hex'),16)*0.2-50   ) 
    
    protrac_packet = protrac.ProtracPacket(packet[0:1].encode('hex'),\
    packet[1:3].encode('hex'),\
    packet[3:6].encode('hex'),\
    packet[6:7].encode('hex'),\
    packet[7:8].encode('hex'),\
    packet[8:9].encode('hex'),\
    packet[9:10].encode('hex'),\
    packet[10:11].encode('hex'),\
    int(packet[11:].encode('hex'),16)*0.2-50,\
    int(time.time()))
    producer.send_message(json.dumps(protrac_packet.__dict__))
    pass

print 'init client'
p = protrac.ProtracClient('/dev/ttyUSB0',115200,io_loop, callback=on_packet)
producer.run()
io_loop.start()
