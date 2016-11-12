# cleanup.py Demo/test program for MicroPython scheduler
# Author: Peter Hinch
# Copyright Peter Hinch 2016 Released under the MIT license
# Flashes the onboard LED's each at a different rate. Stops after ten seconds.

import pyb
from usched import Sched

# Run on MicroPython board bare hardware
# THREADS:
def stop(fTim, objSch):                                     # Stop the scheduler after fTim seconds
    yield fTim
    objSch.stop()

class toggler(object):
    def __init__(self, instance):
        self.instance = instance
    def __enter__(self):
        print('Enter', self.instance)
    def __exit__(self, *args):
        print('Exit', self.instance)

def toggle(objLED, time, instance):
    iteration = 0
    yield
    with toggler(instance):
        while True:
            yield time
            objLED.toggle()
            if iteration == 10:
                print('about to blow...')
            iteration = iteration + 1 if iteration < 10 else 1/0 # Time bomb
    
# USER TEST FUNCTION

def test(duration = 0):
    if duration:
        print("Flash LED's for {:3d} seconds".format(duration))
    print('Interrupt with ctrl-C or wait for deliberate error')
    print('Expect the usual error dump. But should see four exit lines first.')
    leds = [pyb.LED(x) for x in range(1,5)]                 # Initialise all four on board LED's
    objSched = Sched()                                      # Instantiate the scheduler
    for x in range(4):                                      # Create a thread instance for each LED
        objSched.add_thread(toggle(leds[x], 0.2 + x/2, x))
    if duration:
        objSched.add_thread(stop(duration, objSched))       # Commit suicide after specified no. of seconds
    objSched.run()                                          # Run it!

test(20)

