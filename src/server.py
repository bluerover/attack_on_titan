import serial,sys,datetime,os
import tornado
import functools
import errno
import dmtp
import protrac
from tornado.httpserver import HTTPServer
from web import BaseHandler
from dmtp import DmtpClient
from protrac import ProtracClient

NEW_LINE_SEQUENCE = 'aa'
PORT = '/dev/ttyUSB0'
BAUD = 115200
def handle_packet(packet):
    print packet

buffer = None


if __name__ == 'main':
    '''DEVICE = '/dev/ttyUSB0'
    BAUD = 115200
    ser = serial.Serial(DEVICE,BAUD)
    ser.nonblocking()
    def wrapper(s,fd,events):
      try:
        print datetime.datetime.now()
        print ser.read(1).encode('hex')
      except:
        print sys.exc_info()
    io_loop = tornado.ioloop.IOLoop.instance()
    callback = functools.partial(wrapper, serial)
    io_loop.add_handler(ser.fileno(),callback,io_loop.READ)
    '''
    io_loop = tornado.ioloop.IOLoop.instance()
    dmtp_client = DmtpClient()
    def handle_packet(protrac_packet):
        dmtp_client.send_packet()
        
    protrac_client = ProtracClient('/dev/ttyUSB0',115200,io_loop,callback=handle_packet)
    
    services = dict(
        dmtp = dmtp,
        protrac = protrac
        )
    settings = dict(
        template_path=os.path.join(os.path.dirname(__file__), "template"),
        static_path=os.path.join(os.path.dirname(__file__), "static"),
        cookie_secret= 'secret_key',
        login_url='/login'
        )
    application = tornado.web.Application([
    (r"/", BaseHandler, services),
    ], debug=True, **settings)
    sockets = tornado.netutil.bind_sockets(9999)
    server = HTTPServer(application)
    server.add_sockets(sockets)
    
    io_loop.start()
