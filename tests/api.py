import unittest
import tweepy
from timer import Timer
from config import CONSUMER_KEY, CONSUMER_SECRET, RADIUS, DEFAULT
CACHE = tweepy.MemoryCache(600)


class APITests(unittest.TestCase):
    def test_api(self):
        with Timer() as target:
            auth = tweepy.AppAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
            api = tweepy.API(
                auth,
                retry_count=3,
                retry_delay=5,
                retry_errors=set([401, 404, 500, 503]),
                wait_on_rate_limit=True,
                wait_on_rate_limit_notify=True
            )
        print 'API %.2fs' % target.elapsed
        CACHE.store('api', api)

    def test_results(self):
        api = CACHE.get('api')
        with Timer() as target:
            results = api.search(q='vucic', geocode=DEFAULT['geocode'], count=20)
        print 'RES %.2fs' % target.elapsed
        print '----'
        for obj in results:
            print obj.user.screen_name