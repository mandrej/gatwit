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
import pygeoip
import collections
import base64
from datetime import datetime
from tweepy.cache import MemoryCache
from webapp2 import WSGIApplication
from webapp2_extras import jinja2, sessions
from jinja2.utils import Markup
from geopy import geocoders
from geopy.geocoders.googlev3 import GQueryError

CONSUMER_KEY = 'uvkMU4MFVn2N3lgizdFRfQ'
CONSUMER_SECRET = 'HGsVbzsYjCDhI0Y6u2vurlvEWrFqBxZkkQAu2ASnQ'
TOKEN_URL = 'https://api.twitter.com/oauth2/token'

GV3 = geocoders.GoogleV3()
GIP = pygeoip.GeoIP('pygeoip/GeoLiteCity.dat')
CACHE = MemoryCache(600)

DEVEL = os.environ.get('SERVER_SOFTWARE', '').startswith('Dev')
RADIUS = '10km'
# convert -size 48x48 xc:transparent gif:- | base64
BLANK = 'R0lGODlhMAAwAPAAAAAAAAAAACH5BAEAAAAALAAAAAAwADAAAAIxhI+py+0Po5y02ouz3rz7D4biSJbmiabqyrbuC8fyTNf2jef6zvf+DwwKh8Si8egpAAA7'
DEFAULT = {'name': u'Belgrade, Serbia', 'geocode': '44.8205556,20.4622222,%s' % RADIUS}


def year():
    date = datetime.now()
    return date.strftime('%Y')


def twitterize(text):
    text = unicode(text.encode('utf-8'), 'utf-8')
    twit_link = re.compile(r'@(\w+)', re.IGNORECASE)
    hash_link = re.compile(r'#(\w+)', re.IGNORECASE)
    if twit_link.search(text):
        text = twit_link.sub(r'<a class="twit" href="https://twitter.com/\1">@\1</a>', text)
    if hash_link.search(text):
        text = hash_link.sub(r'<a class="hash" href="https://twitter.com/search?q=%23\1&src=hash">#\1</a>', text)
    return Markup(text)


def timesince_jinja(value, default="just now"):
    now = datetime.utcnow()
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
    """ Reverse geocoding
        Args:
            arg (dict): {u'coordinates': [20.4717135, 44.760376], u'type': u'Point'}
            results (list): [(u'OMV pumpa, Belgrade, Serbia', (44.7605262, 20.4730118)), ...]

        Returns:
            str: u'OMV pumpa, Belgrade, Serbia'

    """
    coordinates = arg['coordinates']
    coordinates.reverse()
    point_str = ','.join(map(str, coordinates))
    results = GV3.reverse(point_str, sensor=False)
    location, point = results[0]  # first result
    return location


def geo_location(arg):
    """ Geocoding
        Args:
            arg (str): 'Sabac'
            results (tuple): (u'\u0160abac, Serbia', (44.75423, 19.699751))

        Returns:
            tuple: u'\u0160abac, Serbia', '44.75423,19.699751'

    """
    try:
        results = GV3.geocode(arg, sensor=False)
    except GQueryError as e:
        return None, e.message
    except ValueError as e:
        return None, e.message
    else:
        location, point = results
        return location, ','.join(map(str, point))


class AppAuthHandler(tweepy.auth.AuthHandler):
    # http://shogo82148.github.io/blog/2013/05/09/application-only-authentication-with-tweepy/
    def __init__(self):
        token_credential = urllib.quote(CONSUMER_KEY) + ':' + urllib.quote(CONSUMER_SECRET)
        credential = base64.b64encode(token_credential)

        data = urllib.urlencode({'grant_type': 'client_credentials'})
        req = urllib2.Request(TOKEN_URL)
        req.add_header('Authorization', 'Basic ' + credential)
        req.add_header('Content-Type', 'application/x-www-form-urlencoded;charset=UTF-8')

        response = urllib2.urlopen(req, data)
        json_response = json.loads(response.read())
        self._access_token = json_response['access_token']
        logging.error(self._access_token)

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
        kwargs['city'] = self.session.get('city', DEFAULT)
        self.response.write(self.jinja2.render_template(filename, **kwargs))


class Index(BaseHandler):
    def get(self):
        query = self.request.get('q', '')
        city = self.session.get('city', DEFAULT)

        auth = CACHE.get('auth')
        if auth is None:
            auth = AppAuthHandler()
            CACHE.store('auth', auth)

        # http://www.nirg.net/blog/2013/04/using-tweepy/
        api = tweepy.API(
            [auth],
            retry_count=3,
            retry_delay=5,
            retry_errors=set([401, 404, 500, 503]),
            monitor_rate_limit=True,
            wait_on_rate_limit=True
        )

        collection = api.search(q=query, geocode=city['geocode'], count=20)  # <class 'tweepy.models.ResultSet'>
        # logging.error(vars(collection[0].user))
        self.render_template('index.html', {
            'collection': collection,
            'query': query,
            'radius': RADIUS,
            'flashes': self.session.get_flashes(),
            'blank': 'data:image/gif;base64,%s' % BLANK
        })

    def post(self):
        location, coordinates = geo_location(self.request.get('place'))
        if location is None:
            record = GIP.record_by_addr(self.request.remote_addr)
            if all(['latitude', 'longitude', 'city']) in record:
                geocode = '{0},{1}'.format('{latitude:.4f},{longitude:.4f}'.format(**record), RADIUS)
                self.session['city'] = {'name': record['city'], 'geocode': geocode}
                self.session.add_flash('GeoIP found %s from request.' % record['city'], level='')
            else:
                self.session['city'] = DEFAULT
                self.session.add_flash(coordinates, level='error')
                self.session.add_flash('GeoIP results incomplete.', level='error')
                self.session.add_flash('Using %s as default place.' % DEFAULT['name'], level='')
        else:
            self.session['city'] = {'name': location, 'geocode': '{0},{1}'.format(coordinates, RADIUS)}
            self.session.add_flash('Geocoder found %s' % location, level='')
        self.redirect('/')

CONFIG = {
    'webapp2_extras.jinja2': {
        'globals': {
            'year': year
        },
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
    'webapp2_extras.sessions': {'secret_key': 'bjKqvIazjfbbVOqxSvjkMbBjpu9UA2jl', 'session_max_age': 86400}
}
# < /dev/urandom tr -dc _A-Z-a-z-0-9 | head -c${1:-32};echo;
app = WSGIApplication([
    (r'/', Index),
], config=CONFIG, debug=DEVEL)