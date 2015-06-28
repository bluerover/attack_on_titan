import tornado
from tornado.web import RequestHandler
import dmtp


def BaseHandler(RequestHandler):
    
    def initialize(self,dmtp,protrac):
        self.dmtp = dmtp
        self.protrac = protrac
    
    def get(self):
        self.render('index.html')