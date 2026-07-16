import unittest

from smiley_plot import smile


def test_smile():
    assert smile("nix") == ":) nix"


class SmileTest(unittest.TestCase):
    def test_smile(self):
        self.assertEqual(smile("unittest"), ":) unittest")
