__author__ = 'milan'

from google.appengine.ext import ndb


class UserCredentials(ndb.Model):
    # user.user_id() as ID
    token_key = ndb.StringProperty(required=True)
    token_secret = ndb.StringProperty(required=True)
    access_key = ndb.StringProperty()
    access_secret = ndb.StringProperty()
    oauth_token = ndb.StringProperty()
    oauth_verifier = ndb.StringProperty()
    user = ndb.UserProperty(auto_current_user=True)
    when = ndb.DateTimeProperty(auto_now_add=True)