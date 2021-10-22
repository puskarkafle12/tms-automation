from datetime import datetime
count=0
while(1):
  
    print("Current Time =", datetime.now().strftime("%H:%M:%S.%f")[:-3])
    count=count+1
    print(count)