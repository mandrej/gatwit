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
import logging
import datetime
import pygeoip
from webapp2 import WSGIApplication
from webapp2_extras import sessions, jinja2
from jinja2.utils import Markup

CONSUMER_KEY = 'uvkMU4MFVn2N3lgizdFRfQ'
CONSUMER_SECRET = 'HGsVbzsYjCDhI0Y6u2vurlvEWrFqBxZkkQAu2ASnQ'
if os.environ.get('SERVER_SOFTWARE', '').startswith('Dev'):
    DEVEL = True
    CALLBACK = 'http://localhost:8080/oauth/callback'
else:
    DEVEL = False
    CALLBACK = 'http://gatwitbot.appspot.com/oauth/callback'

RADIUS = '10mi'
GI = pygeoip.GeoIP('pygeoip/GeoLiteCity.dat')
LOCAL_IP = '178.148.225.25'


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


class BaseHandler(webapp2.RequestHandler):
    def dispatch(self):
        # Get a session store for this request.
        self.session_store = sessions.get_store(request=self.request)
        try:
            # Dispatch the request.
            webapp2.RequestHandler.dispatch(self)
        finally:
            # Save all sessions.
            self.session_store.save_sessions(self.response)

    @webapp2.cached_property
    def jinja2(self):
        return jinja2.get_jinja2(app=self.app)

    @webapp2.cached_property
    def session(self):
        """Returns a session using the default cookie key"""
        return self.session_store.get_session(backend='memcache')

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
        self.response.write(self.jinja2.render_template(filename, **kwargs))

    def render_json(self, data):
        self.response.content_type = 'application/json; charset=utf-8'
        self.response.write(json.dumps(data))


class TwitterDecorator(object):
    def __init__(self):
        self.auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET, CALLBACK)

    def oauth_required(self, method):
        def wrapper(handler, *args):
            if handler.session.get('access_token') is None:
                return handler.redirect('/oauth')

            self.auth.set_access_token(*handler.session.get('access_token'))
            handler.api = tweepy.API(self.auth)
            method(handler, *args)
        return wrapper

decorator = TwitterDecorator()


class RequestAuthorization(BaseHandler):
    def get(self):
        self.session['request_token'] = None
        self.session['access_token'] = None
        # Build a new oauth handler and display authorization url to user.
        auth = decorator.auth
        auth_url = auth.get_authorization_url(True)
        self.session['request_token'] = (auth.request_token.key, auth.request_token.secret)
        self.redirect(auth_url)


class CallbackPage(BaseHandler):
    def get(self):
        oauth_verifier = self.request.get('oauth_verifier', None)
        if oauth_verifier is None:
            self.abort(500)

        # Rebuild the auth handler
        auth = decorator.auth
        auth.set_request_token(*self.session.get('request_token'))
        self.session['request_token'] = None

        # Fetch the access token
        auth.get_access_token(oauth_verifier)
        self.session['access_token'] = (auth.access_token.key, auth.access_token.secret)
        self.redirect('/')


class Index(BaseHandler):
    @decorator.oauth_required
    def get(self):
        page = int(self.request.get('page', 1))
        query = self.request.get('q', '')

        user = self.session.get('user')
        if user is None:
            user = self.api.me()
            self.session['user'] = user

        geocode = self.request.get('geocode') or self.session.get('geocode')
        if geocode is None:
            if DEVEL:
                record = GI.record_by_addr(LOCAL_IP)
            else:
                record = GI.record_by_addr(self.request.remote_addr)
            geocode = self.session['geocode'] = '{0},{1}'.format(
                '{latitude:.4f},{longitude:.4f}'.format(**record),
                RADIUS)

        collection = self.api.search(q=query, geocode=geocode, rpp=10, include_entities=True, page=page)
        self.render_template('index.html', {
            'collection': collection,
            'query': query,
            'radius': RADIUS,
            'user': user})


class Retweet(BaseHandler):
    @decorator.oauth_required
    def post(self):
        id = self.request.get('id')
        try:
            status = self.api.retweet(id=id, trim_user=False)
            self.render_json({'success': 'success', 'message': 'Retweeting successful'})
        except tweepy.TweepError, e:
            try:
                self.render_json({'success': 'error', 'message': '{code}: {message}'.format(**e[0][0])})
            except TypeError:
                self.render_json({'success': 'error', 'message': e.reason.capitalize()})


class Reply(BaseHandler):
    @decorator.oauth_required
    def post(self):
        id = self.request.get('id')
        from_user = self.request.get('from')
        text = self.request.get('text', '')  # from post 140 chars max
        try:
            status = self.api.update_status(in_reply_to_status_id=id, status='{0} {1}'.format(from_user, text))
            self.render_json({'success': 'success', 'message': 'Reply successful'})
        except tweepy.TweepError, e:
            try:
                self.render_json({'success': 'error', 'message': '{code}: {message}'.format(**e[0][0])})
            except TypeError:
                self.render_json({'success': 'error', 'message': e.reason.capitalize()})

CONFIG = {
    'webapp2_extras.jinja2': {
        'filters': {
            'twitterize': twitterize,
            'timesince': timesince_jinja
        },
        'environment_args': {
            'autoescape': True,
            'extensions': ['jinja2.ext.autoescape', 'jinja2.ext.with_']
        },
    },
    'webapp2_extras.sessions': {
        'secret_key': 'XbOgZLNTzv5OoO2tBAM+Rw5ewX5d3TxVgvSfRJtc1W4=',
        'backends': {'memcache': 'webapp2_extras.appengine.sessions_memcache.MemcacheSessionFactory'}
    }
}
app = WSGIApplication([
    (r'/', Index),
    (r'/oauth', RequestAuthorization),
    (r'/oauth/callback', CallbackPage),
    (r'/retweet', Retweet),
    (r'/reply', Reply),
], config=CONFIG, debug=DEVEL)