'''
Created on Dec 11, 2009

@author: chris
'''

from google.appengine.ext import db

class RadioProgram(db.Model):
    name = db.StringProperty(required=True)
    host = db.StringProperty(required=True)
    timeslot = db.StringProperty(required=True)
    #timeslot_start = db.DateTimeProperty
    #timeslot_end = db.DateTimeProperty

class Track(db.Model):
    title = db.StringProperty(required=True)
    artist = db.StringProperty(required=True)
    date_added = db.DateTimeProperty(auto_now_add=True)
    times_played = db.IntegerProperty(default=0)
    
class TrackPlayed(db.Model):
    track = db.ReferenceProperty(Track)
    program = db.ReferenceProperty(RadioProgram)
    air_date = db.DateProperty(required=True)