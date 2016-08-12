# syncom.py Synchronous communication channel between two MicroPython
# platforms. 14 Jul 16 

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

# Timing: 4.5mS per char between Pyboard and ESP8266 i.e. ~1.55Kbps

import pickle

_BITS_PER_CH = const(7)
_BITS_SYN = const(8)


class SynCom(object):
    syn = 0x9d

    def __init__(self, objsched, passive, ckin, ckout, din, dout, latency=5,
                 verbose=True):
        self.passive = passive
        self.latency = max(latency, 1)  # No. of bytes between scheduler yield
        self.verbose = verbose
        if verbose:
            self.idstr = 'passive' if self.passive else 'initiator'

        self.ckin = ckin            # Interface pins
        self.ckout = ckout
        self.din = din
        self.dout = dout

        self.indata = 0             # Current data bits
        self.inbits = 0
        self.odata = self.syn
        self.lsttx = []             # Queue of strings to send
        self.lstrx = []             # Queue of received strings

        self.phase = 0              # Interface initial conditions
        if passive:
            self.dout(0)
            self.ckout(0)
        else:
            self.dout(self.odata & 1)
            self.ckout(1)
            self.odata >>= 1        # we've sent that bit
            self.phase = 1
        objsched.add_thread(self._run())


# Queue an object for tx. Convert to string NOW: snapshot of current
# object state
    def send(self, obj):
        self.lsttx.append(pickle.dumps(obj))

    def any(self):
        return len(self.lstrx)

    def get(self):
        if self.any():
            return pickle.loads(self.lstrx.pop(0))

    def _run(self):
        if self.verbose:
            print(self.idstr, ' awaiting sync...')
        yield
        while self.indata != self.syn:  # Don't hog CPU while waiting for start
            yield from self._synchronise()
        self.lstrx = []  # ? Necessary even though done in ctor. Why?
#        self.lsttx = [] No need: allow transmissions to be queued before sync
        if self.verbose:
            print(self.idstr, ' synchronised')

        sendstr = ''                # string for transmission
        send_idx = None             # character index. None: no current string
        getstr = ''                 # receive string
        latency = self.latency      # No of chars to send before yield
        try:
            while True:
                if send_idx is None:
                    if len(self.lsttx):
                        sendstr = self.lsttx.pop(0)  # oldest first
                        send_idx = 0
                if send_idx is not None:
                    if send_idx < len(sendstr):
                        self.odata = ord(sendstr[send_idx])
                        send_idx += 1
                    else:
                        send_idx = None
                if send_idx is None:  # send zeros when nothing to send
                    self.odata = 0
                self._get_byte()
                if self.indata:
                    getstr = ''.join((getstr, chr(self.indata)))
                else:                # Got 0:
                    if len(getstr):  # if there's a string, it's complete
                        self.lstrx.append(getstr)
                    getstr = ''

                latency -= 1
                if latency <= 0:    # yield at intervals of N characters
                    latency = self.latency
                    yield
        finally:
            self.dout(0)
            self.ckout(0)

    def _get_byte(self):
        if self.passive:
            self.indata = self._get_bit(self.inbits)  # MSB is outstanding
            inbits = 0
            for _ in range(_BITS_PER_CH - 1):
                inbits = self._get_bit(inbits)
            self.inbits = inbits
        else:
            inbits = 0
            for _ in range(_BITS_PER_CH):
                inbits = self._get_bit(inbits)  # LSB first
            self.indata = inbits

    def _synchronise(self):         # wait for clock
        while self.ckin() == self.phase ^ self.passive ^ 1:
            yield
        self.indata = (self.indata | (self.din() << _BITS_SYN)) >> 1
        odata = self.odata
        self.dout(odata & 1)
        self.odata = odata >> 1
        self.phase ^= 1
        self.ckout(self.phase)      # set clock

    def _get_bit(self, dest):
        while self.ckin() == self.phase ^ self.passive ^ 1:
            pass
        dest = (dest | (self.din() << _BITS_PER_CH)) >> 1
        obyte = self.odata
        self.dout(obyte & 1)
        self.odata = obyte >> 1
        self.phase ^= 1
        self.ckout(self.phase)
        return dest
