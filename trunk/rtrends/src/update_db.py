from google.appengine.api import urlfetch
from google.appengine.ext import webapp

import sys, re, string, logging
from datetime import datetime, date, tzinfo, timedelta
from delete_tracks import bulkdelete
from Models import RadioProgram, TrackPlayed, Track

progmatcher = re.compile(r"programtimeid=([0-9]+)")
hdrmatcher = re.compile(r"[[][-\w/.,;%&\s]*[]]")
songmatcher = re.compile(r"\t*([\w\S ]+)\t([\w\S ]+)|\t*([\w\S ]+) / ([\w\S ]+)|\t*([\w\S ]+) - ([\w\S ]+)")
#songmatcher = re.compile(r"\s*(\w+\s*)+\t+| / (\w+\s*)+")
datematcher = re.compile(r"\b(0?[1-9]|[12][0-9]|3[01])[-/.](0?[1-9]|1[012])[-/.](\d\d)?\b")
longdatematcher = re.compile(r"([1-9]|[12][0-9]|3[01])(st|nd|rd|th)?")


Weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
Months = ['January', 'February', 'March', 'April', 'May', 'June', 
          'July', 'August', 'September', 'October', 'November', 'December']


class ozdst(tzinfo):
    def utcoffset(self, dt):
        return timedelta(hours=10,minutes=0) + self.dst(dt)
    def _FirstSunday(self, dt):
        """First Sunday on or after dt."""
        return dt + timedelta(days=(6-dt.weekday()))
    def dst(self, dt):
        # 2 am on the second Sunday in October
        dst_start = self._FirstSunday(datetime(dt.year, 10, 4, 2))
        # 3 am on the first Sunday in April
        dst_end = self._FirstSunday(datetime(dt.year, 4, 4, 3))

        if dst_start <= dt.replace(tzinfo=None) or dt.replace(tzinfo=None) < dst_end:
            return timedelta(hours=1)
        else:
            return timedelta(hours=0)
    def tzname(self,dt):
        if self.dst(dt) == timedelta(hours=0):
            return "AEST"
        else:
            return "AEDT"

""" General Strategy for parsing works like this:
(1) fetch the main index (pageid=100)
(1.1) using the program matcher regex, compile a list of programs.
(2) for each program id found, fetch the corresponding program page
(2.1)

"""
class TrackFetcher(webapp.RequestHandler):
    _total_parsed=0
    def ParseDate(self, line, year):
        #date = datetime.strptime("%d/%m/%y")
        dayname, day, month = None, None, None
        maxtokens = 5
        args = line.split(" ", maxtokens)
        maxtokens = len(args)
        thedate = None
        for i in range(maxtokens):
            token = args[i]
            token = token.partition('<')[0]
            if len(token) < 2:
                continue
            if token[0].isalpha():
                string = token.title()
                if dayname is None:
                    matchlist = [w for w in Weekdays if w.startswith(string) ]
                    if len(matchlist):
                        dayname = matchlist[0]
                        logging.debug("DAY=(%s)" %(dayname))
                        continue
                if month is None:
                    matchlist = [n+1 for n,m in enumerate(Months) if m.startswith(string) ]
                    if len(matchlist):
                        month = matchlist[0]
            elif token[0].isdigit():
                print token
                # it's a number, try the short style regex first
                # if we didn't already match a month name
                if month is None:
                    match = datematcher.match(token)
                    if match is not None:
                        matchlist = match.groups()
                        if len(matchlist) < 2:
                            return thedate
                        if len(matchlist) < 3:
                            y = year
                        else:
                            y = matchlist[2]
                        logging.debug("[%s] %s" % (matchlist, line))
                        return date(int(y), int(matchlist[1]), int(matchlist[0]))
                if day is None:
                    matchlist = longdatematcher.match(token)
                    if matchlist is not None:
                        day = int(matchlist.group(1))
                if token.isdigit() and len(token) == 4:
                    if year >= int(token):
                        year = int(token)
            if thedate is None:
                if day is not None and month is not None:
                    logging.info("%d/%d/%d [%s]" % (day, month, year, line))
                    thedate = date(year, month, day)
        return thedate

    def ParseTrack(self, line):
        t = None
        #print "matching line: %s" % (line)
        match = songmatcher.search(line)
    #matchlist = songmatcher.findall(result.content)
    #for item in matchlist:
        if match is not None:
            item = [ x for x in match.groups() if x != None ]
            #print >> sys.stderr, "%s" % (str(match.groups()))
            #if len(item[0]) == 0:
            #    item = item[2:]
            title = string.capwords(item[0].strip('\t /'))
            artist = string.capwords(item[1].strip('\t /'))
            title = title.partition("<")[0]
            artist = artist.partition("<")[0]
            if len(artist) == 0:
                tmp = title.split("/")
                if len(tmp) < 2: 
                    logging.error("unable to parse artist from title: %s" % (title))
                    return None
                title = tmp[0].strip(' ')
                artist = tmp[1].strip(' ')
            q = Track.gql("WHERE title=:1 AND artist=:2", title, artist)
            t = q.get()
            if t is None:
                t = Track(title=title, artist=artist)
                self._total_parsed = self._total_parsed+1
            #print "[%d] %s - %s" % (self._total_parsed, artist, title)
                logging.info("[%d] %s - %s" % (self._total_parsed, t.artist, t.title))

            #histogram[(artist, title)] = histogram.get((artist, title),0)+1
        else:
            #print "--- skip line: " + line
            pass
        return t
    
    def ParseProgramTracks(self, programid):
        #print i
        _program = None
        _date = None
        _urlStr = "http://www.fbiradio.com/program_closeup.php?programtimeid=" + str(programid)
        _result = urlfetch.fetch(_urlStr)
        if _result.status_code != 200:
            logging.error("No Program matches id=" + str(programid))
            return
        logging.info("scraping program with id=" + str(programid))
        #default the year to now
        year = int(datetime.now().year)
        # search for matching programs using header regex
        for line in _result.content.splitlines():
            if _program is None:
                matchlist = hdrmatcher.findall(line)
                # if there are more than two items matching then we have a header
                if len(matchlist) > 2:
                    name = matchlist[0]
                    host = matchlist[1]
                    timeslot = matchlist[2]
                    q = RadioProgram.gql("WHERE host=:1 AND name=:2 AND timeslot=:3", host, name, timeslot)
                    _program = q.get()
                    if _program is None:
                        _program = RadioProgram(host=host, name=name, timeslot=timeslot)
                        _program.put()
                    logging.info("[%d] Program='%s' host='%s' timeslot='%s'" % (programid, _program.name,_program.host,_program.timeslot))
                else:
                    logging.debug("Trouble matching hdr with id=" +str(programid))
                continue
            # try and match a date string to assign to individual tracks
            d = self.ParseDate(line, year)
            if d is not None:
                _date = d
                year = _date.year
            # now try and match individual songs, 
            # nb multiple strategies may need to be attempted
            t = self.ParseTrack(line)
            if t is not None:
                t.times_played = t.times_played+1
                t.put()
                if _date is None:
                    logging.warning("Unable to save track [%s-%s] play out, no air date found"% (t.artist, t.title))
                    return
                q = TrackPlayed.gql("WHERE track=:1 AND program=:2 AND air_date=:3", t.key(), _program.key(), _date)
                tp = q.get()
                if tp is None:
                    tp = TrackPlayed(track=t, program=_program, air_date=_date)
                    tp.put()
                else:
                    logging.warning("*** Duplicate track entry [%s-%s] for date (%s)" % (t.artist, t.title, _date.strftime("%d-%m-%y")))
                    continue
        return 
    
    def ParseProgramIndex(self, mainurl):
        programs = []
        result = urlfetch.fetch(mainurl)
        if result.status_code != 200:
            logging.error("Unable to parse main program index at url=%s" % (mainurl))
            return
        now = datetime.now(ozdst())
        logging.info("BEGIN scrape job")
        hour=-2
        day=0
        columns = [0,0,0,0,0,0,0]  # array of 7 days
        for item in result.content.splitlines():
            # now find the first column with zero span
            if any(x == 0 for x in columns):
                day = columns.index(0)
            if "<th " in item:
                hour=hour+1
                # subtract default span from each column
                #print >> sys.stderr, "th [%d,%d,%d,%d,%d,%d,%d]" % (columns[0],columns[1],columns[2],columns[3],columns[4],columns[5],columns[6])
                
                for i,x in enumerate(columns):
                    if x >= 4:
                        columns[i] = x-4
                #else:
                #    day = 0
            if "<td rowspan=" in item:
                #print >> sys.stderr, "td [%d,%d,%d,%d,%d,%d,%d]" % (columns[0],columns[1],columns[2],columns[3],columns[4],columns[5],columns[6])
                span = int(item.split('"')[1]) #parse the rowspan
                
                columns[day] = columns[day] + span
            match = progmatcher.search(item)
            if match is not None:
                program = match.group(1)
                if (now.weekday() == day) and (now.hour - hour >= 3) and (now.hour - hour <= 6):
                    programs.append(int(program))
        #download those programs and if they are new we should schedule for parsing
        #logging.info("found %d programs within window" % (len(programs))
        for i in programs:
            self.ParseProgramTracks(i)
        logging.info("END scrape job")
    
    def DisplayTopTracks(self):
        print "---TOP TRACKS---"
        top_tracks = Track.gql("ORDER BY times_played DESC LIMIT 10")
        #print "Total tracks:" + str(len(histogram.values()))
        #sorted(histogram.iteritems, key=operator.itemgetter(1), reverse=True)
        for item in top_tracks.run(): #heapq.nlargest(20,histogram.iteritems(),operator.itemgetter(1)):
            print "[%d] %s - %s" % (item.times_played, string.ljust(item.artist,40), string.ljust(item.title,40))
    def DisplayAllTracks(self):
        print "---TOTAL TRACKS: %d---" % (self._total_parsed)
        all_tracks = Track.gql("ORDER BY date_added DESC")
        for item in all_tracks.run():
            print "[%d] %s - %s" % (item.times_played, string.ljust(item.artist,40), string.ljust(item.title,40))

    def ParseDateAlt(self, line, year):
        date_formats_with_year = ['%d %m %Y', '%d %B %Y', '%B %d %Y', 
                                              '%d %b %Y', '%b %d %Y',
                                  '%d %m %y', '%d %B %y', '%B %d %y',
                                              '%d %b %y', '%b %d %y']

        date_formats_without_year = ['%d %B', '%B %d',
                                     '%d %b', '%b %d', 
                                     '%d %m', '%m %d']
        line = line.partition("<")[0]
        string = line.strip().split(" ", 4)
        if not string[0].isdigit() and len(string[0]) > 2:
            matchlist = [w for w in Weekdays if w.startswith(str(string[0]).title()) ]
            if len(matchlist):
                dayname = matchlist[0]
                del string[0]
        string = " ".join(string)
        print >> sys.stderr, "%s" % (string)
        if not string: return None
        string = string.replace('/',' ').replace('-',' ').replace(',',' ')
        
        for format in date_formats_with_year:
            try:
                result = datetime.strptime(string, format)
                print >> sys.stderr, "%d/%d/%d [%s]" % (result.day,result.month,result.year, line)
                return date(result.year, result.month, result.day)
            except ValueError:
                pass
    
        for format in date_formats_without_year:
            try:
                result = datetime.strptime(string, format)
                print >> sys.stderr, "%d/%d/%d [%s]" % (result.day,result.month,result.year, line)
                return date(year, result.month, result.day)
            except ValueError:
                pass
        return None


def main():
    #    def get(self):
    print 'Content-Type: text/plain'
    print ''
    #self.response.headers['Content-Type'] = 'text/plain'
    mainurl = "http://www.fbiradio.com/content.php/100.html"
    d = bulkdelete()
    d.delete_tracks()
    fetcher = TrackFetcher()
    fetcher.ParseProgramIndex(mainurl)
    fetcher.DisplayTopTracks()
    fetcher.DisplayAllTracks()

if __name__ == "__main__":
    main()

#print histogram
#return
#result = urlfetch.fetch(urlStr)
#if result.status_code == 200:
#
#    print 'Content-Type: application/rss+xml'
#    print ''
#
#    print """<?xml version="1.0"?>
#    <rss version="2.0">
#      <channel>
#        <title>Teardrop downloads feed</title>
#        <link>http://www.teardrop.fr/download/</link>
#        <description>RSS 2.0 feed containing the latest Teardrop downloads</description>
#        <language>en-us</language>
#        <generator>rssGoogleCode, crafted by Olivier Coupelon</generator>
#        <webMaster>olivier.coupelon@teardrop.fr</webMaster>"""
#
#    for m in re.finditer(reGoogleCode, result.content):
#        print '    <item>'
#        print '      <title>%s</title>' % m.group(3)
#        print '      <link>%s</link>' % m.group(1)
#        print '      <description>%s</description>' % m.group(2)
#        print '    </item>'
#
#    print """  </channel>
#    </rss>"""
#
#print 'Content-Type: text/plain'
#print ''
#print 'Hello, world!'

