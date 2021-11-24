import math
ltp=1424.9
changePercentage=0.99
if changePercentage>7.84:
                    # solving equations we get
        high_price=110*ltp/(changePercentage+100)
else:
        high_price=ltp+2/100*ltp
high_price=math.floor(high_price * 10 ** 1) / 10 ** 1
print(high_price)

