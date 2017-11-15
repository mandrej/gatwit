import unittest
from timer import Timer
from geopy.distance import vincenty
from geopy.geocoders import GoogleV3
GV3 = GoogleV3()


class GeoCodersTests(unittest.TestCase):
    def setUp(self):
        pass

    def test_geocode(self):
        with Timer() as target:
            loc = GV3.geocode('OMV pumpa, Belgrade', exactly_one=True)

        print 'Geocoder %.2fs' % target.elapsed
        print(loc.address, loc.latitude, loc.longitude)

        northeast = loc.raw['geometry']['bounds']['northeast'].values()
        southwest = loc.raw['geometry']['bounds']['southwest'].values()
        print vincenty(northeast, southwest).kilometers

    def test_reverse_geocode(self):
        with Timer() as target:
            loc = GV3.reverse('44.8205556, 20.4622222', exactly_one=True)

        print 'Reverse geocoder %.2fs' % target.elapsed
        print(loc.address, loc.latitude, loc.longitude)