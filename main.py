__author__ = 'milan'

import os
import json
import webapp2
import jinja2
import time
import tweepy
import urllib
import logging
import datetime
from tweepy.utils import unescape_html
from google.appengine.api import users
from webapp2 import WSGIApplication
from webapp2_extras.jinja2 import get_jinja2
from webapp2_extras.appengine.users import login_required
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


def quote(s):
    return urllib.quote_plus(s)


def unquote(s):
    return urllib.unquote_plus(s)


# https://twitter.com/search?q=%23energyideas&src=hash
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
    'quote': quote,
    'unquote': unquote,
    'timesince': timesince_jinja,
})

class BaseHandler(webapp2.RequestHandler):
    @webapp2.cached_property
    def user(self):
        return users.get_current_user()

    @webapp2.cached_property
    def jinja2(self):
        return get_jinja2(app=self.app)

    def render_template(self, filename, kwargs):
        template = ENV.get_template(filename)
        self.response.write(template.render(kwargs))

    def render_json(self, data):
        self.response.content_type = 'application/json; charset=utf-8'
        self.response.write(json.dumps(data))


class RequestAuthorization(BaseHandler):
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
    def get(self):
        oauth_token = self.request.get("oauth_token", None)
        oauth_verifier = self.request.get("oauth_verifier", None)
        if oauth_token is None:
            # Invalid request!
            self.render_template('error.html', {"message": 'Missing required parameters!'})

        # Lookup the request token
        credentials = UserCredentials.get_by_id(oauth_token)
        if credentials is None:
            # We do not seem to have this request token, show an error.
            self.render_template('error.html', {"message": 'No credentials'})

        # Rebuild the auth handler
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(credentials.token_key, credentials.token_secret)

        # Fetch the access token
        try:
            auth.get_access_token(oauth_verifier)
        except tweepy.TweepError, e:
            # Failed to get access token
            self.render_template('error.html', {"message": e})

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
            logging.info('RequestAuthorization')
            return self.redirect('/oauth')

        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(credentials.token_key, credentials.token_secret)
        auth.set_access_token(credentials.access_key, credentials.access_secret)

        page = int(self.request.get('page', 1))
        query = unquote(self.request.get('q', 'night'))
        geocode = unquote(self.request.get('geocode', '44.833,20.463,20km'))

        auth_api = tweepy.API(auth)
        collection = auth_api.search(q=query, geocode=geocode, rpp=10, page=page, count=20)

        self.render_template('index.html', {
            'collection': collection,
            'me': auth_api.me(),
            'logout_url': users.create_logout_url('/')})


app = WSGIApplication([
    (r'/', Index),
    (r'/oauth', RequestAuthorization),
    (r'/oauth/callback', CallbackPage),
], debug=True)