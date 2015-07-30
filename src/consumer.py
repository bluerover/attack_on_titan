from pika import adapters
import pika
import logging
import functools
from rabbit import RabbitConnection,Producer,Consumer

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

def main():
    try:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
        io_loop = tornado.ioloop.IOLoop.instance()
        #consumer = Consumer('amqp://guest:guest@localhost:5672/%2F',io_loop)
        tag_dictionary = dict()    
        processed = set()
        def on_message(body,*args):
            json.loads(ProtracPacket)
            print(body)
            
        def on_timer():
            processed.clear()
            for k,v in tag_dictionary.iteritems():
                if not(k in processed):
                    '''(self,cust_num,tag_num,rssi,reader_id,battery,flags,temperature):'''
                    dmtp_packet = DMTPTagInRangePacket(v.cust_num, v.tag_num,v.rssi,0,v.battery,v.flag,v.temperature)
                    del tag_dictionary[k]
                    producer.send_message(json.dumps(dmtp_packet.__dict__))
                    processed.add(k)
                
        consumer = Consumer('amqp://guest:guest@localhost:5672/%2F',io_loop,on_message)
        producer = Producer('amqp://guest:guest@localhost:5672/%2F',io_loop)
        producer.QUEUE = "dmtp"
        producer.EXCHANGE = "upstream"
        consumer.run()
        producer.run()
                
        periodic_callback = tornado.ioloop.PeriodicCallback(on_timer, 5000,io_loop=io_loop)
        periodic_callback.start()
        io_loop.start()
    except KeyboardInterrupt:
        consumer.stop()
        producer.stop()
        io_loop.stop()
    

if __name__ == '__main__':
    main()