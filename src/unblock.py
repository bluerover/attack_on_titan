from threading import Thread
import functools
import tornado
from tornado import gen
import logging,sys
logging.basicConfig(level=logging.DEBUG)


from futures import ThreadPoolExecutor
from functools import partial, wraps        
EXECUTOR = ThreadPoolExecutor(max_workers=4)
'''Wrapped classes must implement on_finish_block callback'''
def unblock(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            def callback(future):
                try:
                    if(kwargs.has_key('callback')):
                        params = future.result()
                        if params:
                            kwargs.pop('callback')(*params) 
                            logging.debug("called func %s" % callback)
                    else:
                        logging.debug("no callback specified")
                        return
                except:
                    logging.error(sys.exc_info())
            io_loop = None   
            #check if the self object has its own io_loop defined :s
            if(hasattr(args[0],'io_loop')):
                io_loop = args[0].io_loop
            else :
                io_loop = tornado.ioloop.IOLoop.instance()
            #execute our function in the threadpool
            EXECUTOR.submit(
                partial(f, *args, **kwargs)
            ).add_done_callback(
                lambda future: io_loop.add_callback(
                    partial(callback, future)))
        return wrapper
