import unittest

from utils.tms import TmsUser


class TestTradebookPagination(unittest.TestCase):
    def test_merge_single_unpaginated_response_larger_than_page_size(self):
        rows = [{"id": index} for index in range(26)]
        merged = TmsUser._merge_tradebook_pages([rows], page_size=10)
        self.assertEqual(len(merged), 26)

    def test_merge_multiple_pages(self):
        page_one = [{"id": index} for index in range(10)]
        page_two = [{"id": index} for index in range(10, 15)]
        merged = TmsUser._merge_tradebook_pages([page_one, page_two], page_size=10)
        self.assertEqual(len(merged), 15)

    def test_merge_stops_on_empty_page(self):
        page_one = [{"id": index} for index in range(10)]
        merged = TmsUser._merge_tradebook_pages([page_one, []], page_size=10)
        self.assertEqual(len(merged), 10)

    def test_merge_respects_total_pages(self):
        page_one = [{"id": index} for index in range(10)]
        page_two = [{"id": index} for index in range(10, 20)]
        merged = TmsUser._merge_tradebook_pages([page_one, page_two], page_size=10, total_pages=2)
        self.assertEqual(len(merged), 20)
