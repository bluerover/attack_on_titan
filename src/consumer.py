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


tag_dictionary = dict()
def main():
    try:
	config = ConfigParser.SafeConfigParser({"accountId":None,"deviceId":None,"dmtp_url":'dmtp://54.84.59.135:21000'})
	config.read("settings.cfg")
	print config.get("dmtp","dmtp_url")
	print config.get("dmtp","accountId")
	print config.get("dmtp","deviceId")

        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
        ioloop = tornado.ioloop.IOLoop()
        #tag_dictionary = dict()    
        processed = set()
	client = None #SimpleAsyncDmtpClient(ioloop)
	consumer = None
	producer = None
	convert = ['rssi','cust_num','flags','battery','tag_num','tag_seq','recv_bytes','switch_count']
	def on_message(body):
            #pp = ProtracPacket(**json.loads(body))
            #print("on message")
	    #print(body)
	    try:
		d = json.loads(body)
	        tag_dictionary[d['tag_num']] = d
	    except:
	    	logging.error("exception in asynchronous operation",exc_info=True)
	    logging.info("finished processing message")
	    #raise "Dont want to remove off queue"
	
	def on_response(response):
	    print(response)
	    if response.error:
		print("errror sending packet")
	    else:
		print("tag in range sent")

        def on_timer():
	    print("running timer")
	    global client
	    global tag_dictionary
	    for k,d in tag_dictionary.iteritems():
            	print("processing packet %s"%k)
		for prop in convert:
                    d[prop] = int(d[prop],16)
                print(d)
                try:
		    d['rssi'] = d['rssi']-128
		    dmtp_packet = DMTPTagInRangePacket(**d)
		    dmtp_request = DMTPRequest(\
		    config.get("dmtp","dmtp_url"),\
		    config.get("dmtp","accountId"),\
		    config.get("dmtp","deviceId"),\
		    packets=[dmtp_packet])
		    client.fetch(dmtp_request,on_response)	
		except:
   		    logging.error("exception in asynchronous operation",exc_info=True)
	    tag_dictionary = dict()
	    print("clear dictionary")
	    return

	consumer = Consumer('amqp://guest:guest@localhost:5672/%2F',ioloop,on_message)
        #producer = Producer('amqp://guest:guest@localhost:5672/%2F',ioloop)
        #producer.QUEUE = "dmtp"
        #producer.EXCHANGE = "upstream"
        #consumer.run()
        #producer.run()
        print("Start timer")
	def run_loop(on_timer):
	    thread_ioloop = tornado.ioloop.IOLoop() 
	    global client
	    global producer
	    producer = Producer('amqp://guest:guest@localhost:5672/%2F',thread_ioloop)
            producer.QUEUE = "dmtp"
            producer.EXCHANGE = "upstream"
	    client = SimpleAsyncDmtpClient(thread_ioloop) 
	    periodic_callback = tornado.ioloop.PeriodicCallback(on_timer,\
		config.getint("dmtp","timer"),io_loop=thread_ioloop)
            periodic_callback.start()        
	    producer.run()
            thread_ioloop.start()
	thread = Thread(target = run_loop,args=(on_timer,))
	thread.daemon = True
	thread.start()
	#periodic_callback = tornado.ioloop.PeriodicCallback(on_timer, 10000,io_loop=ioloop)
        #periodic_callback.start()
        consumer.run() 
	ioloop.start()
    except KeyboardInterrupt:
        consumer.stop()
        #producer.stop()
        ioloop.stop()
    

if __name__ == '__main__':
    main()
