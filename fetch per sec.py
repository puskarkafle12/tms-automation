import threading
import time
count=0
previous_count=0
sec=3#second for showing fetch per sec
def printit():
    global previous_count
    threading.Timer(sec, printit).start()
    print ("fetched per second",round((count-previous_count)/sec,2))
    previous_count=count
printit()


while(1):
    time.sleep(0.2)
    count=count+1
