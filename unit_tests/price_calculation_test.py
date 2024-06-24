import os
import sys
import unittest
import math

sys.path.append('/Users/pkafle/tms-automation')
from utils.base_functions import calculate_high_price
# def calculate_high_price(ltp, change_in_percentage):
#     if change_in_percentage > 7.843:
#         original_price = ltp*100/(change_in_percentage+100)
#         ten_percent_change = (original_price * 10/ 100 )+ original_price
#         high_price = math.floor(ten_percent_change * 10 ** 1) / 10 ** 1
#         return high_price

#     high_price = ltp + (2 / 100) * ltp
#     # truncating the decimal e.g., 12.343 to 12.3
#     high_price = math.floor(high_price * 10 ** 1) / 10 ** 1
#     return high_price

class TestCalculateHighPrice(unittest.TestCase):

   
    def test1(self):
        result = calculate_high_price(100,2)
        self.assertEqual(result, 102) 
   
    def test2(self):
        result = calculate_high_price(991.5,10)
        self.assertEqual(result, 991.5)
        
    def test3(self):
        result = calculate_high_price(991.5,7)
        self.assertEqual(result, 1011.3) 
    def test4(self):
        result = calculate_high_price(452.47,0)
        self.assertEqual(result,461.5) 
    def tes5(self):
        result = calculate_high_price(208.30,9.98)
        self.assertEqual(result, 208.30) 
    def test6(self):
        result = calculate_high_price(351.5,9.91)
        self.assertEqual(result, 351.7) 
    def test7(self):
        result = calculate_high_price(141,-0.704225)
        self.assertEqual(result, 143.8) 

if __name__ == '__main__':
    unittest.main()
