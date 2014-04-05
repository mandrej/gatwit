__author__ = 'milan'
# -*- coding: utf-8 -*-

import os
import sys
import traceback
import re
import json
import webapp2
import tweepy
import urllib
import urllib2
import logging
import datetime
import pygeoip
import collections
import base64
from tweepy.cache import MemoryCache
from webapp2 import WSGIApplication
from webapp2_extras import jinja2, sessions
from jinja2.utils import Markup
from geopy import geocoders

CONSUMER_KEY = 'uvkMU4MFVn2N3lgizdFRfQ'
CONSUMER_SECRET = 'HGsVbzsYjCDhI0Y6u2vurlvEWrFqBxZkkQAu2ASnQ'
TOKEN_URL = 'https://api.twitter.com/oauth2/token'
DEVEL = os.environ.get('SERVER_SOFTWARE', '').startswith('Dev')
GI = pygeoip.GeoIP('pygeoip/GeoLiteCity.dat')
RADIUS = '20mi'
CACHE = MemoryCache(600)
G = geocoders.GoogleV3()
# convert -size 48x48 xc:transparent gif:- | base64
BLANK = 'R0lGODlhMAAwAPAAAAAAAAAAACH5BAEAAAAALAAAAAAwADAAAAIxhI+py+0Po5y02ouz3rz7D4biSJbmiabqyrbuC8fyTNf2jef6zvf+DwwKh8Si8egpAAA7'
CITY = collections.OrderedDict([
    (u'---', 'Automatic'),
    (u'Novi Sad', '45.26353,19.84388'),
    (u'Beograd', '44.82056,20.46222'),
    (u'Smederevo', '44.66667,20.93333'),
    # (u'Požarevac', '44.61667,21.18333'),
    (u'Šabac', '44.75423,19.69975'),
    (u'Valjevo', '44.27437,19.89110'),
    (u'Kragujevac', '44.01271,20.92674'),
    (u'Jagodina', '43.98139,21.24556'),
    (u'Zaječar', '43.92048,22.27742'),
    (u'Čačak', '43.88891,20.35038'),
    (u'Kraljevo', '43.72342,20.68697'),
    (u'Niš', '43.31938,21.89633'),
    (u'Leskovac', '43.00000,21.95000'),
    # (u'CT', '42.39089,18.91398'),
    # (u'PG', '42.44257,19.26865'),
    # (u'BD', '42.28806,18.84250'),
    # (u'BR', '42.09383,19.10027'),
])


def twitterize(text):
    text = unicode(text.encode('utf-8'), 'utf-8')
    twit_link = re.compile(r'@(\w+)', re.IGNORECASE)
    hash_link = re.compile(r'#(\w+)', re.IGNORECASE)
    if twit_link.search(text):
        text = twit_link.sub(r'<a href="https://twitter.com/\1">@\1</a>', text)
    if hash_link.search(text):
        text = hash_link.sub(r'<a class="hash" href="https://twitter.com/search?q=%23\1&src=hash">#\1</a>', text)
    return Markup(text)


def timesince_jinja(value, default="just now"):
    now = datetime.datetime.utcnow()
    diff = now - value
    periods = (
        (diff.days / 365, "year", "years"),
        (diff.days / 30, "month", "months"),
        (diff.days / 7, "week", "weeks"),
        (diff.days, "day", "days"),
        (diff.seconds / 3600, "hour", "hours"),
        (diff.seconds / 60, "minute", "minutes"),
        (diff.seconds, "second", "seconds"),
    )
    for period, singular, plural in periods:
        if period:
            return "%d %s ago" % (period, singular if period == 1 else plural)
    return default


def geo_address(arg):
    # {u'coordinates': [20.3854038, 44.851479], u'type': u'Point'} <type 'dict'>
    coordinates = arg['coordinates']
    coordinates.reverse()
    point_str = ','.join(map(str, coordinates))
    results = G.reverse(point_str, sensor=False)
    location, point = results[0]
    return location


class AppAuthHandler(tweepy.auth.AuthHandler):
    # http://shogo82148.github.io/blog/2013/05/09/application-only-authentication-with-tweepy/
    def __init__(self, consumer_key, consumer_secret):
        token_credential = urllib.quote(consumer_key) + ':' + urllib.quote(consumer_secret)
        credential = base64.b64encode(token_credential)

        value = {'grant_type': 'client_credentials'}
        data = urllib.urlencode(value)
        req = urllib2.Request(TOKEN_URL)
        req.add_header('Authorization', 'Basic ' + credential)
        req.add_header('Content-Type', 'application/x-www-form-urlencoded;charset=UTF-8')

        response = urllib2.urlopen(req, data)
        json_response = json.loads(response.read())
        self._access_token = json_response['access_token']

    def apply_auth(self, url, method, headers, parameters):
        headers['Authorization'] = 'Bearer ' + self._access_token


class BaseHandler(webapp2.RequestHandler):
    def dispatch(self):
        self.session_store = sessions.get_store(request=self.request)
        try:
            webapp2.RequestHandler.dispatch(self)
        finally:
            self.session_store.save_sessions(self.response)

    @webapp2.cached_property
    def jinja2(self):
        return jinja2.get_jinja2(app=self.app)

    @webapp2.cached_property
    def session(self):
        return self.session_store.get_session()

    @webapp2.cached_property
    def session_store(self):
        return sessions.get_store(request=self.request)

    def handle_exception(self, exception, debug):
        code = 500
        data = {}
        if isinstance(exception, webapp2.HTTPException):
            code = exception.code
            data['error'] = exception
        elif isinstance(exception, tweepy.error.TweepError):
            data['lines'] = ''.join(traceback.format_exception(*sys.exc_info()))
            try:
                data['error'] = '{code}: {message}'.format(**exception[0][0])
            except TypeError:
                data['error'] = exception.reason
        else:
            data['error'] = exception
            data['lines'] = ''.join(traceback.format_exception(*sys.exc_info()))

        self.render_template('error.html', data)
        self.response.set_status(code)

    def render_template(self, filename, kwargs):
        kwargs['city'] = self.session.get('city', 'Beograd')
        self.response.write(self.jinja2.render_template(filename, **kwargs))

    def render_json(self, data):
        self.response.content_type = 'application/json; charset=utf-8'
        self.response.write(json.dumps(data))


class Index(BaseHandler):
    def get(self):
        query = self.request.get('q', '')
        city = self.session.get('city', 'Beograd')

        if city == '---':
            record = GI.record_by_addr(self.request.remote_addr)
            if all(['latitude', 'longitude', 'city']) in record:
                geocode = '{0},{1}'.format('{latitude:.4f},{longitude:.4f}'.format(**record), RADIUS)
            else:
                geocode = '{0},{1}'.format(CITY['Beograd'], RADIUS)
                self.session['city'] = '---'
        else:
            try:
                geocode = '{0},{1}'.format(CITY[city], RADIUS)
            except KeyError:
                geocode = '{0},{1}'.format(CITY['Beograd'], RADIUS)
                self.session['city'] = 'Beograd'

        api = CACHE.get('api')
        if api is None:
            auth = AppAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
            # http://www.nirg.net/blog/2013/04/using-tweepy/
            api = tweepy.API(
                [auth],
                retry_count=3,
                retry_delay=5,
                retry_errors=set([401, 404, 500, 503]),
                monitor_rate_limit=True,
                wait_on_rate_limit=True
            )
            CACHE.store('api', api)

        collection = api.search(q=query, geocode=geocode, count=20)  # <class 'tweepy.models.ResultSet'>
        # logging.error(vars(collection[0].user))
        self.render_template('index.html', {
            'collection': collection,
            'query': query,
            'cities': CITY,
            'blank': 'data:image/gif;base64,%s' % BLANK
        })

    def post(self):
        self.session['city'] = self.request.get('place')
        self.render_json(True)


CONFIG = {
    'webapp2_extras.jinja2': {
        'filters': {
            'twitterize': twitterize,
            'timesince': timesince_jinja,
            'geo_address': geo_address
        },
        'environment_args': {
            'autoescape': True,
            'extensions': ['jinja2.ext.autoescape', 'jinja2.ext.with_']
        }
    },
    'webapp2_extras.sessions': {'secret_key': 'bjKqvIazjfbbVOqxSvjkMbBjpu9UA2jl'}
}
# < /dev/urandom tr -dc _A-Z-a-z-0-9 | head -c${1:-32};echo;
app = WSGIApplication([
    (r'/', Index),
], config=CONFIG, debug=DEVEL)