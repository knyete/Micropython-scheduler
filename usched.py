# Lightweight threading library for the micropython board.
# Author: Peter Hinch
# V1.03 Implements gc
# Copyright Peter Hinch 2016 Released under the MIT license

import pyb, micropython, gc
micropython.alloc_emergency_exception_buf(100)

# TIMER ACCESS

TIMERPERIOD = 0x7fffffff                        # 35.79 minutes 2148 secs
MAXTIME     = TIMERPERIOD//2                    # 1073 seconds maximum timeout
MAXSECS     = MAXTIME//1000000

class TimerException(Exception) : pass

def microsWhen(timediff):                       # Expected value of counter in a given no. of uS
    if timediff >= MAXTIME:
        raise TimerException()
    return (pyb.micros() + timediff) & TIMERPERIOD

def microsSince(oldtime):                       # No of uS since timer held this value
    return (pyb.micros() - oldtime) & TIMERPERIOD

def after(trigtime):                            # If current time is after the specified value return
    res = ((pyb.micros() - trigtime) & TIMERPERIOD) # the no. of uS after. Otherwise return zero
    if res >= MAXTIME:
        res = 0
    return res

def microsUntil(tim):                           # uS from now until a specified time (used in Delay class)
    return ((tim - pyb.micros()) & TIMERPERIOD)

def seconds(S):                                 # Utility functions to convert to integer microseconds
    return int(1000000*S)

def millisecs(mS):
    return int(1000*mS)

# WAITFOR CLASS
# This is a base class. User threads should use classes derived from this.

class Waitfor(object):
    def __init__(self):
        self.uS = 0                             # Current value of timeout in uS
        self.timeout = microsWhen(0)            # End value of microsecond counter when TO has elapsed
        self.forever = False                    # "infinite" time delay flag
        self.irq = None                         # Interrupt vector no
        self.pollfunc = None                    # Function to be called if we're polling
        self.pollfunc_args = ()                 # Arguments for the above
        self.customcallback = None              # Optional custom interrupt handler
        self.interruptcount = 0                 # Set by handler, tested by triggered()
        self.roundrobin = False                 # If true reschedule ASAP

    def triggered(self):                        # Polled by scheduler. Returns a priority tuple or None if not ready
        if self.irq:                            # Waiting on an interrupt
            self.irq.disable()                  # Potential concurrency issue here (????)
            numints = self.interruptcount       # Number of missed interrupts
            if numints:                         # Waiting on an interrupt and it's occurred
                self.interruptcount = 0         # Clear down the counter
            self.irq.enable()
            if numints:
                return (numints, 0, 0)
        if self.pollfunc:                       # Optional function for the scheduler to poll
            res = self.pollfunc(*self.pollfunc_args) # something other than an interrupt
            if res is not None:
                return (0, res, 0)
        if not self.forever:                    # Check for timeout
            if self.roundrobin:
                return (0,0,0)                  # Priority value of round robin thread
            res = after(self.timeout)           # uS after, or zero if not yet timed out in which case we return None
            if res:                             # Note: can never return (0,0,0) here!
                return (0, 0, res)              # Nonzero means it's timed out
        return None                             # Not ready for execution

    def _ussetdelay(self, uS=None):             # Reset the timer by default to its last value
        if uS:                                  # If a value was passed, update it
            self.uS = uS
        self.timeout = microsWhen(self.uS)      # Target timer value
        return self

    def setdelay(self, secs=None):              # Method used by derived classes to alter timer values
        if secs is None:                        # Set to infinity
            self.forever = True
            return self
        else:                                   # Update saved delay and calculate a new end time
            self.forever = False
            return self._ussetdelay(seconds(secs))

    def __call__(self):                         # Convenience function allows user to yield an updated
        if self.uS:                             # waitfor object
            return self._ussetdelay()
        return self

    def intcallback(self, irqno):               # Runs in interrupt's context.
        if self.customcallback:
            self.customcallback(irqno)
        self.interruptcount += 1                # Increments count to enable trigger to operate

class Roundrobin(Waitfor):
    def __init__(self):
        super().__init__()
        self.roundrobin = True

# Intended for device drivers
class Timeout(Waitfor):
    def __init__(self, tim):
        super().__init__()
        self.setdelay(tim)

# yield from wait
def wait(secs):
    if secs <=0 :
        raise TimerException()
    count, tstart = divmod(secs, MAXSECS)
    overshoot = 0
    if tstart > 0:
        res = yield Timeout(tstart)
        overshoot = res[2]
    while count:
        res = yield Timeout(MAXSECS)
        overshoot += res[2]
        count -= 1
    return (0, 0, overshoot)

# Block on an interrupt from a pin subject to optional timeout
class Pinblock(Waitfor):
    def __init__(self, pin, mode, pull, customcallback = None, timeout = None):
        super().__init__()
        self.customcallback = customcallback
        if timeout is None:
            self.forever = True
        else:
            self.setdelay(timeout)
        self.irq = pyb.ExtInt(pin, mode, pull, self.intcallback)

class Poller(Waitfor):
    def __init__(self, pollfunc, pollfunc_args = (), timeout = None):
        super().__init__()
        self.pollfunc   = pollfunc
        self.pollfunc_args = pollfunc_args
        if timeout is None:
            self.forever = True
        else:
            self.setdelay(timeout)

# SCHEDULER CLASS

class Sched(object):
    GCTIME = 50000
    def __init__(self):
        self.lstThread = []                                 # Entries contain [Waitfor object, function]
        self.bStop = False
        self.last_gc = 0

    def stop(self):                                         # Kill _runthreads method
        self.bStop = True

    def add_thread(self, func):                             # Thread list contains [Waitfor object, generator]
        try:                                                # Run thread to first yield to acquire a Waitfor instance
            self.lstThread.append([func.send(None), func])  # and put the resultant thread onto the threadlist
        except StopIteration:                               # Onn 1st call implies thread lacks a yield statement
            print("Stop iteration error")

    def run(self):                                          # Run scheduler but trap ^C for testing
        try:
            self._runthreads()
        except OSError as v:                                # Doesn't recognise EnvironmentError or VCPInterrupt!
            print(v)
            print("Interrupted")

    def _idle_thread(self):                                  # Runs once then in roundrobin or when there's nothing else to do
        if self.last_gc == 0 or microsSince(self.last_gc) > self.GCTIME:
            gc.collect()
            self.last_gc = pyb.micros()

    def _runthreads(self):                                  # Only returns if the stop method is used or all threads terminate
        self._idle_thread()
        while len(self.lstThread) and not self.bStop:       # Run until last thread terminates or the scheduler is stopped
            self.lstThread = [thread for thread in self.lstThread if thread[1] is not None] # Remove threads flagged for deletion
            lstPriority = []                                # List threads which are ready to run
            lstRoundRobin = []                              # Low priority round robin threads
            for idx, thread in enumerate(self.lstThread):   # Put each pending thread on priority or round robin list
                priority = thread[0].triggered()            # (interrupt count, poll func value, uS overdue) or None
                if priority is not None:                    # Ignore threads waiting on events or time
                    if priority == (0,0,0) :                # (0,0,0) indicates round robin
                        lstRoundRobin.append(idx)
                    else:                                   # Thread is ready to run
                        lstPriority.append((priority, idx)) # List threads ready to run
            lstPriority.sort()                              # Lowest priority will be first in list

            while True:                                     # Until there are no round robin threads left
                while len(lstPriority):                     # Execute high priority threads first
                    priority, idx = lstPriority.pop(-1)     # Get highest priority thread. Thread:
                    thread = self.lstThread[idx]            # thread[0] is the current waitfor instance, thread[1] is the code
                    try:                                    # Run thread, send (interrupt count, poll func value, uS overdue)
                        thread[0] = thread[1].send(priority)  # Thread yields a Waitfor object: store it for subsequent testing
                    except StopIteration:                   # The thread has terminated:
                        self.lstThread[idx][1] = None       # Flag thread for removal

                if len(lstRoundRobin) == 0:                 # There are no round robins pending. Quit the loop to rebuild new
                    self._idle_thread()
                    break                                   # lists of threads
                idx = lstRoundRobin.pop()                   # Run an arbitrary round robin thread and remove from pending list
                thread = self.lstThread[idx]
                try:                                        # Run thread, send (0,0,0) because it's a round robin
                    thread[0] = thread[1].send((0,0,0))     # Thread yields a Waitfor object: store it
                except StopIteration:                       # The thread has terminated:
                    self.lstThread[idx][1] = None           # Flag thread for removal
                                                            # Rebuild priority list: time has elapsed and events may have occurred!
                for idx, thread in enumerate(self.lstThread): # check and handle priority threads
                    priority = thread[0].triggered()        # (interrupt count, poll func value, uS overdue) or None
                                                            # Ignore pending threads, those scheduled for deletion and round robins
                    if priority is not None and priority != (0,0,0) and thread[1] is not None:
                         lstPriority.append((priority, idx)) # Just list threads wanting to run
                lstPriority.sort()
