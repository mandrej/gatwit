# -*- coding: utf-8 -*-

import os
import sys
import traceback
import re
import urllib
import webapp2
import logging
import pygeoip
import datetime
import tweepy
from webapp2 import WSGIApplication
from webapp2_extras import jinja2, sessions
from google.appengine import runtime
from google.appengine.runtime import apiproxy_errors
from google.appengine.api import urlfetch_errors
from jinja2.utils import Markup
from timeit import default_timer as timer
from geopy.geocoders import GoogleV3
from config import CONSUMER_KEY, CONSUMER_SECRET, RADIUS, DEFAULT, THREAD_LEVEL

GV3 = GoogleV3()
GIP = pygeoip.GeoIP('pygeoip/GeoLiteCity.dat', flags=pygeoip.MEMORY_CACHE)
CACHE = tweepy.MemoryCache(3600)
DEVEL = os.environ.get('SERVER_SOFTWARE', '').startswith('Dev')

# convert -size 48x48 xc:transparent gif:- | base64
BLANK = 'R0lGODlhMAAwAPAAAAAAAAAAACH5BAEAAAAALAAAAAAwADAAAAIxhI+py+0Po5y02ouz3rz7D4biSJbmiabqyrbuC8fyTNf2jef6zvf+DwwKh8Si8egpAAA7'
logging.getLogger().setLevel(logging.DEBUG)


def timeit(f):
    def wrapper(*args, **kw):
        start = timer()
        result = f(*args, **kw)
        end = timer()
        logging.info('func:%r args:[%r, %r] took: %2.4f sec' % (f.__name__, args, kw, end - start))
        return result
    return wrapper


def year():
    date = datetime.datetime.now()
    return date.strftime('%Y')


def twitterize(text):
    text = unicode(text.encode('utf-8'), 'utf-8')
    twit_link = re.compile(r'@(\w+)', re.IGNORECASE)
    hash_link = re.compile(r'#(\w+)', re.IGNORECASE)
    if twit_link.search(text):
        text = twit_link.sub(r'<a class="twit" href="http://twitter.com/\1" target="_blank">@\1</a>', text)
    if hash_link.search(text):
        text = hash_link.sub(r'<a class="hash" href="http://twitter.com/search?q=%23\1&src=hash" target="_blank">#\1</a>', text)
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
    """ Reverse geocoding
        Args:
            arg (dict): {u'coordinates': [20.4717135, 44.760376], u'type': u'Point'}
            results (tuple): (u'OMV pumpa, Belgrade, Serbia', (44.7605262, 20.4730118))

        Returns:
            str: u'OMV pumpa, Belgrade, Serbia'

    """
    coordinates = arg['coordinates']
    coordinates.reverse()
    point_str = ','.join(map(str, coordinates))
    loc = GV3.reverse(point_str, sensor=False, exactly_one=True)
    return loc.address


def geo_location(arg):
    """ Geocoding
        Args:
            arg (str): 'Sabac'
            results (tuple): (u'\u0160abac, Serbia', (44.75423, 19.699751))

        Returns:
            tuple: u'\u0160abac, Serbia', '44.75423,19.699751'

    """
    loc = GV3.geocode(arg, sensor=False, exactly_one=True)
    if loc:
        return loc.address, ','.join(map(str, (loc.latitude, loc.longitude)))
    else:
        return None, 'Geocoder nothing found'


def get_api():
    """
    auth._access_token

    https://dev.twitter.com/docs/auth/oauth/faq
    We do not currently expire access tokens. Your access token will be invalid if a user explicitly rejects
    your application from their settings or if a Twitter admin suspends your application. If your application
    is suspended there will be a note on your application page saying that it has been suspended.
    """
    api = CACHE.get('api')
    if api is None:
        auth = tweepy.AppAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        api = tweepy.API(
            auth,
            retry_count=3,
            retry_delay=5,
            retry_errors=set([401, 404, 500, 503]),
            wait_on_rate_limit=True,
            wait_on_rate_limit_notify=True
        )
        CACHE.store('api', api)
    return api


def get_status(id):
    """
    tweepy.TweepError: [{u'code': 179, u'message': u'Sorry, you are not authorized to see this status.'}]
    Corresponds with HTTP 403 - thrown when a Tweet cannot be viewed by the authenticating user,
    usually due to the tweet's author having protected their tweets.
    """
    api = get_api()
    try:
        status = api.get_status(id)
    except (runtime.DeadlineExceededError,
            apiproxy_errors.DeadlineExceededError,
            urlfetch_errors.DeadlineExceededError,
            tweepy.TweepError) as e:
        return None
    return status


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
        elif isinstance(exception, tweepy.TweepError):
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


class Search(BaseHandler):
    def get(self):
        params = dict(self.request.GET)
        query = params.get('q', '')
        max_id = params.get('max_id')
        city = self.session.get('city', DEFAULT)

        api = get_api()
        results = api.search(q=query, geocode=city['geocode'], max_id=max_id, count=20)

        params['q'] = query.encode('utf-8')
        if results.max_id:
            params['max_id'] = results.max_id

        self.render_template('index.html', {
            'tweets': results,
            'thread_level': THREAD_LEVEL,
            'query': query,
            'params': urllib.urlencode(params),
            'radius': RADIUS,
            'flashes': self.session.get_flashes(),
            'blank': 'data:image/gif;base64,%s' % BLANK
        })

    def post(self):
        new_place = self.request.get('place').strip()
        if new_place == '':
            record = GIP.record_by_addr(self.request.remote_addr)
            if record and all(['latitude', 'longitude', 'city']) in record:
                geocode = '{0},{1}'.format('{latitude:.4f},{longitude:.4f}'.format(**record), RADIUS)
                self.session['city'] = {'name': record['city'], 'geocode': geocode}
                self.session.add_flash('GeoIP found %s from request.' % record['city'], level='')
                logging.info('GeoIP found %s from request.' % record['city'])
            else:
                self.session['city'] = DEFAULT
                self.session.add_flash('GeoIP results incomplete.', level='error')
                self.session.add_flash('Using %s as default place.' % DEFAULT['name'], level='')
        else:
            location, coordinates = geo_location(new_place)
            if location:
                geocode = '{0},{1}'.format(coordinates, RADIUS)
                self.session['city'] = {'name': location, 'geocode': geocode}
                self.session.add_flash('Geocoder found %s' % location, level='')
                logging.info('Geocoder found %s' % location)
            else:
                self.session['city'] = DEFAULT
                self.session.add_flash(coordinates, level='error')
                self.session.add_flash('Using %s as default place.' % DEFAULT['name'], level='')

        self.redirect('/')


class TimeLine(BaseHandler):
    def get(self, name):
        params = dict(self.request.GET)
        max_id = params.get('max_id')

        api = get_api()
        results = api.user_timeline(screen_name=name, max_id=max_id, count=20)

        if results.max_id:
            params['max_id'] = results.max_id

        self.render_template('index.html', {
            'tweets': results,
            'thread_level': THREAD_LEVEL,
            'name': name,
            'params': urllib.urlencode(params),
            'radius': RADIUS,
            'flashes': self.session.get_flashes(),
            'blank': 'data:image/gif;base64,%s' % BLANK
        })


CONFIG = {
    'webapp2_extras.jinja2': {
        'globals': {
            'year': year
        },
        'filters': {
            'twitterize': twitterize,
            'timesince': timesince_jinja,
            'geo_address': geo_address,
            'get_status': get_status
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
    webapp2.Route(r'/', handler=Search),
    webapp2.Route(r'/timeline/<name:\w+>', handler=TimeLine),
], config=CONFIG, debug=DEVEL)