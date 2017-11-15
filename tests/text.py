# -*- coding: utf-8 -*-

import re
import unittest


class HashTest(unittest.TestCase):
    def setUp(self):
        self.text = 'RT @MONDO_MobIT: Ne šaljite prostačke #SMS poruke za Uskrs! Umesto toga pošaljite e-jaje, koje ste sami ofarbali :) http://t.co/mFpoWCypIr @Mondoportal #Egg'

    def test_replace(self):
        twit_link = re.compile(r'@(\w+)', re.IGNORECASE)
        hash_link = re.compile(r'#(\w+)', re.IGNORECASE)
        if twit_link.search(self.text):
            self.text = twit_link.sub(r'<a class="twit" href="http://twitter.com/\1" target="_blank">@\1</a>', self.text)
        if hash_link.search(self.text):
            self.text = hash_link.sub(r'<a class="hash" href="http://twitter.com/search?q=%23\1&src=hash" target="_blank">#\1</a>', self.text)
        print self.text
