# sr_init.py Test of synchronous comms library. Initiator end.

# The MIT License (MIT)
#
# Copyright (c) 2016 Peter Hinch
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

# Run on Pyboard
from machine import Pin
from usched import Sched
from syncom import SynCom
import utime

def initiator_thread(chan):
    yield
    so = ['test', 0, 0]
    for x in range(4):          # Test full duplex by sending 4 in succession
        so[1] = x
        chan.send(so)
        yield
    while True:                 # Receive the four responses
        if chan.any():          # Deal with queue
            si = chan.get()
            print('initiator received', si)
            if si[1] == 3:      # received last one
                break
        yield
    while True:                 # At 2 sec intervals send an object and get response
        yield 2
        tim = utime.ticks_ms()
        chan.send(so)
        while not chan.any():   # wait for response
            yield
        so = chan.get()
        duration = utime.ticks_diff(tim, utime.ticks_ms())
        print('initiator received', so, 'timing', duration)

def test():
    stx = Pin(Pin.board.Y5, Pin.OUT_PP)         # Define pins
    sckout = Pin(Pin.board.Y6, Pin.OUT_PP)
    sckout.value(0) # Don't assert clock until data is set
    srx = Pin(Pin.board.Y7, Pin.IN)
    sckin = Pin(Pin.board.Y8, Pin.IN)
    reset = Pin(Pin.board.Y4, Pin.OPEN_DRAIN)

    objsched = Sched(heartbeat = 1)
    channel = SynCom(objsched, False, sckin, sckout, srx, stx)
    channel.start(reset, 0)
    objsched.add_thread(initiator_thread(channel))
    try:
        objsched.run()
    finally:
        sckout.value(0)

