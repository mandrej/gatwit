__author__ = 'milan'

import unittest
import tweepy
from timer import Timer

CONSUMER_KEY = 'uvkMU4MFVn2N3lgizdFRfQ'
CONSUMER_SECRET = 'HGsVbzsYjCDhI0Y6u2vurlvEWrFqBxZkkQAu2ASnQ'
CACHE = tweepy.MemoryCache(600)


class APITests(unittest.TestCase):
    def test_api(self):
        with Timer() as target:
            auth = CACHE.get('auth')
            if auth is None:
                auth = tweepy.AppAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
                CACHE.store('auth', auth)
        print 'AUTH %.2fs' % target.elapsed

        with Timer() as target:
            api = tweepy.API(auth, retry_count=3, retry_delay=5)
        print 'API %.2fs' % target.elapsed