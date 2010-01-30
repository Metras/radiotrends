'''
Created on Dec 13, 2009

@author: chris
'''
import time, sys
from google.appengine.ext import db
from google.appengine.ext import webapp
from Models import Track

class bulkdelete(webapp.RequestHandler):
    def delete_tracks(self):
        try:
            print "deleting tracks"
            while True:
                q = db.GqlQuery("SELECT __key__ FROM Track")
                assert q.count()
                db.delete(q.fetch(200))
                print >> sys.stderr, "."
                time.sleep(0.5)
        except Exception, e:
            print repr(e);
        #    self.response.out.write(repr(e)+'\n')
            pass
    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'
        self.delete_tracks()
