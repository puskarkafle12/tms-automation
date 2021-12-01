import math
ltp=1618.5
changePercentage=8.2391
if changePercentage>7.8431372:
                    # solving equations we get
        high_price=110*ltp/(changePercentage+100)
else:
        high_price=ltp+2/100*ltp
high_price=math.floor(high_price * 10 ** 1) / 10 ** 1
print(high_price)

