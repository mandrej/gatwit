__author__ = 'milan'

import os
import json
import webapp2
import jinja2
import tweepy
from google.appengine.api import users
from webapp2 import WSGIApplication
from webapp2_extras.jinja2 import get_jinja2
from webapp2_extras.appengine.users import login_required
from models import OAuthToken

import logging

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')
ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
    autoescape=True
)

CONSUMER_KEY = '6GuIfrWPKuAp7UDMT17GA'
CONSUMER_SECRET = '6IqWHpS3MkU2XsnIzehvfctTHnqEs3hOPWFznijRzG4'
CALLBACK = 'http://gatwitbot.appspot.com/oauth/callback'


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


class MainPage(BaseHandler):
    @login_required
    def get(self):
        self.render_template('home.html', {
            "user": self.user,
            "logout_url": users.create_logout_url('/')})


class RequestAuthorization(BaseHandler):
    @login_required
    def get(self):
        # Build a new oauth handler and display authorization url to user.
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET, CALLBACK)
        auth_url = auth.get_authorization_url()
        # We must store the request token for later use in the callback page.
        request_token = OAuthToken.get_or_insert(
            auth.request_token.key,
            token_key=auth.request_token.key,
            token_secret=auth.request_token.secret
        )
        # request_token = OAuthToken(
        #     token_key=auth.request_token.key,
        #     token_secret=auth.request_token.secret,
        # )
        request_token.put()
        self.redirect(auth_url)


class CallbackPage(BaseHandler):
    def get(self):
        oauth_token = self.request.get("oauth_token", None)
        oauth_verifier = self.request.get("oauth_verifier", None)
        if oauth_token is None:
            # Invalid request!
            self.render_template('error.html', {"message": 'Missing required parameters!'})

        # Lookup the request token
        request_token = OAuthToken.get_by_id(oauth_token)
        # request_token = OAuthToken.gql("WHERE token_key = :key", key=oauth_token).get()
        if request_token is None:
            # We do not seem to have this request token, show an error.
            self.render_template('error.html', {"message": 'Invalid token!'})

        # Rebuild the auth handler
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(request_token.token_key, request_token.token_secret)

        # Fetch the access token
        try:
            auth.get_access_token(oauth_verifier)
        except tweepy.TweepError, e:
            # Failed to get access token
            self.render_template('error.html', {"message": e})

        request_token.access_key = auth.access_token.key
        request_token.access_secret = auth.access_token.secret
        request_token.oauth_token = oauth_token
        request_token.oauth_verifier = oauth_verifier
        request_token.put()

        self.redirect('/home')


class Home(BaseHandler):
    @login_required
    def get(self):
        dbauth = OAuthToken.query(OAuthToken.user == self.user, OAuthToken.access_key != None).get()
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(dbauth.key.id(), dbauth.token_secret)
        auth.set_access_token(dbauth.access_key, dbauth.access_secret)

        auth_api = tweepy.API(auth)
        me = auth_api.me()
        page_list = []  # auth_api.friends(me)
        for page in tweepy.Cursor(auth_api.home_timeline, count=30).pages(2):
            page_list.append(page)

        self.render_template('twitter_home.html', {
            'collection': page_list,
            'me': me.screen_name,
            'logout_url': users.create_logout_url('/')})


app = WSGIApplication([
    (r'/', MainPage),
    (r'/oauth', RequestAuthorization ),
    (r'/oauth/callback', CallbackPage),
    (r'/home', Home),
], debug=True)