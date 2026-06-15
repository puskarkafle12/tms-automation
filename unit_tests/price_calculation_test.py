import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from utils.base_functions import calculate_high_price, is_stock_grabber_stop_reached

class TestCalculateHighPrice(unittest.TestCase):

   
    def test1(self):
        result = calculate_high_price(100,2)
        self.assertEqual(result, 102) 
   
    def test2(self):
        result = calculate_high_price(991.5,10)
        self.assertEqual(result, 1036.5)
        
    def test3(self):
        result = calculate_high_price(991.5,7)
        self.assertEqual(result, 1011.3) 
    def test4(self):
        result = calculate_high_price(452.47,0)
        self.assertEqual(result,461.5) 
    def test5(self):
        result = calculate_high_price(208.30,9.98)
        self.assertEqual(result, 217.8)
    def test6(self):
        result = calculate_high_price(351.5,9.91)
        self.assertEqual(result, 367.7)
    def test7(self):
        result = calculate_high_price(141,-0.704225)
        self.assertEqual(result, 143.8) 

    def test_caps_target_at_new_fifteen_percent_limit(self):
        result = calculate_high_price(115, 15)
        self.assertEqual(result, 115)

    def test_stop_buy_after_user_threshold(self):
        self.assertFalse(is_stock_grabber_stop_reached(8.9, 9))
        self.assertTrue(is_stock_grabber_stop_reached(9, 9))
        self.assertTrue(is_stock_grabber_stop_reached(0, 0))

    def test_stop_buy_threshold_is_clamped_to_fifteen_percent(self):
        self.assertFalse(is_stock_grabber_stop_reached(14.9, 20))
        self.assertTrue(is_stock_grabber_stop_reached(15, 20))

if __name__ == '__main__':
    unittest.main()
