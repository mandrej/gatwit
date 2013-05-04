__author__ = 'milan'
# -*- coding: utf-8 -*-

import os
import sys
import traceback
import re
import json
import webapp2
import jinja2
import time
import tweepy
import urllib
import logging
import datetime
from google.appengine.api import users
from webapp2 import WSGIApplication
from webapp2_extras.jinja2 import get_jinja2
from webapp2_extras.appengine.users import login_required
from jinja2.utils import Markup
from models import UserCredentials

CONSUMER_KEY = '6GuIfrWPKuAp7UDMT17GA'
CONSUMER_SECRET = '6IqWHpS3MkU2XsnIzehvfctTHnqEs3hOPWFznijRzG4'
if os.environ.get('SERVER_SOFTWARE', '').startswith('Dev'):
    CALLBACK = 'http://127.0.0.1:8080/oauth/callback'
else:
    CALLBACK = 'http://gatwitbot.appspot.com/oauth/callback'

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')
ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
    autoescape=True
)


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

ENV.filters.update({
    'timesince': timesince_jinja,
    'twitterize': twitterize,
})


class BaseHandler(webapp2.RequestHandler):
    @webapp2.cached_property
    def user(self):
        return users.get_current_user()

    @webapp2.cached_property
    def jinja2(self):
        return get_jinja2(app=self.app)

    def handle_exception(self, exception, debug):
        template = ENV.get_template('error.html')
        if isinstance(exception, webapp2.HTTPException):
            data = {'error': exception, 'path': self.request.path_qs}
            self.render_template(template, data)
            self.response.set_status(exception.code)
        if isinstance(exception, tweepy.error.TweepError):
            data = {'error': exception.reason}
            self.render_template(template, data)
            self.response.set_status(500)
        else:
            data = {'error': exception, 'lines': ''.join(traceback.format_exception(*sys.exc_info()))}
            self.render_template(template, data)
            self.response.set_status(500)

    def render_template(self, filename, kwargs):
        template = ENV.get_template(filename)
        self.response.write(template.render(kwargs))

    def render_json(self, data):
        self.response.content_type = 'application/json; charset=utf-8'
        self.response.write(json.dumps(data))


class RequestAuthorization(BaseHandler):
    @login_required
    def get(self):
        # Build a new oauth handler and display authorization url to user.
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET, CALLBACK)
        auth_url = auth.get_authorization_url()
        credentials = UserCredentials.get_or_insert(
            auth.request_token.key,
            token_key=auth.request_token.key,
            token_secret=auth.request_token.secret
        )
        credentials.put()
        self.redirect(auth_url)


class CallbackPage(BaseHandler):
    @login_required
    def get(self):
        oauth_token = self.request.get("oauth_token", None)
        oauth_verifier = self.request.get("oauth_verifier", None)
        if oauth_token is None:
            self.abort(401)

        # Lookup the credentials
        credentials = UserCredentials.get_by_id(oauth_token)
        if credentials is None:
            self.abort(500)

        # Rebuild the auth handler
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(credentials.token_key, credentials.token_secret)

        # Fetch the access token
        try:
            auth.get_access_token(oauth_verifier)
        except tweepy.error.TweepError:
            self.abort(500)

        credentials.access_key = auth.access_token.key
        credentials.access_secret = auth.access_token.secret
        credentials.oauth_token = oauth_token
        credentials.oauth_verifier = oauth_verifier
        credentials.put()
        time.sleep(1)
        self.redirect('/')


class Index(BaseHandler):
    @login_required
    def get(self):
        credentials = UserCredentials.query(UserCredentials.user == self.user).get()
        if credentials is None:
            logging.info('Request Authorization')
            return self.redirect('/oauth')

        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(credentials.token_key, credentials.token_secret)
        auth.set_access_token(credentials.access_key, credentials.access_secret)

        page = int(self.request.get('page', 1))
        query = self.request.get('q', '')
        geocode = self.request.get('geocode', '44.833,20.463,20km')

        auth_api = tweepy.API(auth)
        try:
            me = auth_api.me()
            collection = auth_api.search(q=query, geocode=geocode, rpp=10, include_entities=True, page=page)
        except tweepy.error.TweepError:
            self.abort(500)

        self.render_template('index.html', {'collection': collection, 'query': query, 'me': me})


app = WSGIApplication([
    (r'/', Index),
    (r'/oauth', RequestAuthorization),
    (r'/oauth/callback', CallbackPage),
], debug=True)