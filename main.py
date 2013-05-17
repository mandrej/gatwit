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
from webapp2 import WSGIApplication
from webapp2_extras import sessions, jinja2
from jinja2.utils import Markup

TITLE = 'lajna'
CONSUMER_KEY = '6GuIfrWPKuAp7UDMT17GA'
CONSUMER_SECRET = '6IqWHpS3MkU2XsnIzehvfctTHnqEs3hOPWFznijRzG4'
if os.environ.get('SERVER_SOFTWARE', '').startswith('Dev'):
    CALLBACK = 'http://127.0.0.1:8080/oauth/callback'
else:
    CALLBACK = 'http://gatwitbot.appspot.com/oauth/callback'


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
        template = 'error.html'
        if isinstance(exception, webapp2.HTTPException):
            data = {'error': exception, 'title': TITLE}
            self.render_template(template, data)
            self.response.set_status(exception.code)
        else:
            data = {'error': exception, 'lines': ''.join(traceback.format_exception(*sys.exc_info())), 'title': TITLE}
            self.render_template(template, data)
            self.response.set_status(500)

    def render_template(self, filename, kwargs):
        self.response.write(self.jinja2.render_template(filename, **kwargs))

    def render_json(self, data):
        self.response.content_type = 'application/json; charset=utf-8'
        self.response.write(json.dumps(data))


class RequestAuthorization(BaseHandler):
    def get(self):
        # Build a new oauth handler and display authorization url to user.
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET, CALLBACK)
        auth_url = auth.get_authorization_url()
        self.session['token_key'] = auth.request_token.key
        self.session['token_secret'] = auth.request_token.secret
        self.redirect(auth_url)


class CallbackPage(BaseHandler):
    def get(self):
        oauth_token = self.request.get("oauth_token", None)
        oauth_verifier = self.request.get("oauth_verifier", None)
        if oauth_token is None:
            self.abort(500)

        # Rebuild the auth handler
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(self.session.get('token_key'), self.session.get('token_secret'))

        # Fetch the access token
        auth.get_access_token(oauth_verifier)
        self.session['access_key'] = auth.access_token.key
        self.session['access_secret'] = auth.access_token.secret
        self.redirect('/')


class Index(BaseHandler):
    def get(self):
        tokens = [
            self.session.get('token_key'),
            self.session.get('token_secret'),
            self.session.get('access_key'),
            self.session.get('access_secret')
        ]
        if any(tok is None for tok in tokens):
            return self.redirect('/oauth')

        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(self.session.get('token_key'), self.session.get('token_secret'))
        auth.set_access_token(self.session.get('access_key'), self.session.get('access_secret'))
        auth_api = tweepy.API(auth)

        page = int(self.request.get('page', 1))
        query = self.request.get('q', '')
        geocode = self.request.get('geocode', '44.833,20.463,20km')

        screen_name = self.session.get('screen_name', None)
        if screen_name is None:
            screen_name = self.session['user'] = auth_api.me().screen_name

        collection = auth_api.search(
            q=query,
            geocode=geocode,
            rpp=10,
            include_entities=True,
            page=page,
            retry_count=3)
        self.render_template('index.html', {
            'collection': collection,
            'query': query,
            'title': '{0} {1}'.format(screen_name, TITLE)})


# class Reply(BaseHandler):
#     def post(self, id_str):
#         credentials = UserCredentials.get_by_id(self.user.user_id())
#         if credentials is None:
#             logging.info('Request Authorization')
#             return self.redirect('/oauth')
#
#         auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
#         auth.set_request_token(credentials.token_key, credentials.token_secret)
#         auth.set_access_token(credentials.access_key, credentials.access_secret)
#         auth_api = tweepy.API(auth)
#
#         text = urllib.quote(self.request.get('text', ''))  # from post 140 chars max
#         reply = auth_api.update_status('@{0} {1}'.format(auth_api.me(), text), id_str)

app = WSGIApplication([
    (r'/', Index),
    (r'/oauth', RequestAuthorization),
    (r'/oauth/callback', CallbackPage),
], config=CONFIG, debug=True)