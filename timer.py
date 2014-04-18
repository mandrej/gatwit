__author__ = 'milan'

from timeit import default_timer


class Timer(object):
    def __init__(self):
        self.timer = default_timer
        self.start = 0
        self.elapsed = 0

    def __enter__(self):
        self.start = self.timer()
        return self

    def __exit__(self, *args):
        end = self.timer()
        self.elapsed = end - self.start # sec