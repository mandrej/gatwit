__author__ = 'milan'

import unittest
import pygeoip
GIP = pygeoip.GeoIP('../pygeoip/GeoLiteCity.dat')


class GeoIPTests(unittest.TestCase):
    def setUp(self):
        self.ip = '24.135.51.78'

    def test_ip(self):
        record = GIP.record_by_addr(self.ip)
        for k, v in record.items():
            print '%s:\t%s' % (k, v)