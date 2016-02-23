# instrument.py Demo of instrumenting code via the usched module's timer functions
# Author: Peter Hinch
# Copyright Peter Hinch 2016 Released under the MIT license

import pyb
from usched import Sched, Roundrobin, wait, microsSince

# Run on MicroPython board bare hardware
# THREADS:

def instrument(objSched=None, interval=0.1, duration=10):
    if interval == 0 or interval > duration:
        raise ValueError('Arguments are invalid')
    count = duration // interval
    max_overrun = 0
    while count:
        count -= 1
        result = yield from wait(interval)
        max_overrun = max(max_overrun, result[2])
    print('Maximum overrun = {}us'.format(max_overrun))
    if objSched is not None:
        objSched.stop()

def thr_instrument(objSch, lstResult):
    yield Roundrobin()                          # Don't measure initialisation phase (README.md)
    while True:
        start = pyb.micros()                    # More typically we'd measure our own code
        yield Roundrobin()                      # but here we're measuring yield delays
        lstResult[0] = max(lstResult[0], microsSince(start))
        lstResult[1] += 1

def robin(text):
    wf = Roundrobin()
    while True:
        print(text)
        yield wf()

# USER TEST PROGRAM

def test(duration):
    assert duration >= 1, 'Duration must be at least one second'
    objSched = Sched()
    objSched.add_thread(robin("Thread 1"))      # Instantiate a few threads
    objSched.add_thread(robin("Thread 2"))
    objSched.add_thread(robin("Thread 3"))
    lstResult = [0, 0]
    objSched.add_thread(thr_instrument(objSched, lstResult))
    objSched.add_thread(instrument(objSched, 0.1, duration))
    objSched.run()
    print("Maximum delay was {:6.1f}mS".format(lstResult[0]/1000.0))
    print("Thread was executed {:3d} times in {:3d} seconds".format(lstResult[1], duration))

test(2)

