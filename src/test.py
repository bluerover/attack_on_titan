import tornado
import protrac
import datetime
from tornado import ioloop

io_loop = tornado.ioloop.IOLoop.instance()

def cb(packet):
  print datetime.datetime.now() 
  print 'rssi:%s custNum:%s tagNum:%s tagSeq:%s switchCount:%s batter:%s flags:%s recv byte:%s temperature:%s '%(packet[0:1].encode('hex'),\
		packet[1:3].encode('hex'),\
		packet[3:6].encode('hex'),\
		packet[6:7].encode('hex'),\
		packet[7:8].encode('hex'),\
		packet[8:9].encode('hex'),\
		packet[9:10].encode('hex'),\
		packet[10:11].encode('hex'),\
		int(packet[11:].encode('hex'),16)*0.2-50   ) 
  pass

print 'init client'
p = protrac.ProtracClient('/dev/ttyUSB0',115200,io_loop, callback=cb)

io_loop.start()
