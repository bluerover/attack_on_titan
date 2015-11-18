from pika import adapters
import pika
import logging
import functools
from rabbit import RabbitConnection,Producer,Consumer
from dmtp import *
LOG_FORMAT = ('%(levelname) -10s %(asctime)s %(name) -30s %(funcName) '
              '-35s %(lineno) -5d: %(message)s')
LOGGER = logging.getLogger(__name__)
import tornado
import datetime
from tornado import ioloop
from multiprocessing import Manager
from protrac import ProtracPacket
from dmtp import DMTPTagInRangePacket
import json 
import ConfigParser
from threading import Thread
import pickle
import pika
def main():
    try:
	config = ConfigParser.SafeConfigParser({"accountId":None,"deviceId":None,"dmtp_url":'dmtp://54.84.59.135:21000'})
	config.read("settings.cfg")
	print config.get("dmtp","dmtp_url")
	print config.get("dmtp","accountId")
	print config.get("dmtp","deviceId")

        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
        ioloop = tornado.ioloop.IOLoop()
	client = SimpleAsyncDmtpClient(ioloop)
	
	def on_response(response):
	    print(response)
	    if response.error:
		print("errror sending packet")
	    else:
		print("tag in range sent")
	
	@gen.coroutine
        def on_message(body):
	    print(body)    
	    print("received packet")
	    #global client
	    
	    dmtp_packet = pickle.loads(body)
	    dmtp_request = DMTPRequest(\
		    config.get("dmtp","dmtp_url"),\
		    config.get("dmtp","accountId"),\
		    config.get("dmtp","deviceId"),\
		    packets=[dmtp_packet])
	    #yield DMTPResponse Object
	    response = yield client.fetch(dmtp_request)	
	    if not(response.code == 200):
		raise "Error sending data"
	
	    return

	consumer = Consumer('amqp://guest:guest@localhost:5672/%2F',ioloop,on_message)
        consumer.QUEUE = 'dmtp'
	consumer.EXCHANGE = 'upstream'
	consumer.run()
	ioloop.start()
    except KeyboardInterrupt:
        consumer.stop()
        ioloop.stop()
    

if __name__ == '__main__':
    main()
