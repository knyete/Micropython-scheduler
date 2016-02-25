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

class Roundrobin(Waitfor):                      # Compatibility only. A thread yielding a Roundrobin
    def __init__(self):                         # will be rescheduled as soon as priority threads have been serviced
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
    GCTIME = const(50000)
    DEAD = const(0)
    RUNNING = const(1)
    PAUSED = const(2)
    WAITFOR = const(0)
    FUNC = const(1)
    PID = const(2)
    STATE = const(3)
    def __init__(self):
        self.lstThread = []                     # Entries contain [Waitfor object, function, pid, state]
        self.bStop = False
        self.last_gc = 0
        self.pid = 0

    def __getitem__(self, pid):                 # Index by pid
        threads = [thread for thread in self.lstThread if thread[PID] == pid]
        if len(threads) == 1:
            return threads[0]
        elif len(threads) == 0:
            raise ValueError('Unknown thread ID {}'.format(pid))
        else:
            raise OSError('Scheduler fault: duplicate thread {}'.format(pid))

    def stop(self, pid=0):
        if pid == 0:
            self.bStop = True                   # Kill _runthreads method
            return
        self[pid][STATE] = DEAD

    def pause(self, pid):
        print('pause pid', pid)
        self[pid][STATE] = PAUSED

    def resume(self, pid):
        print('resume pid', pid)
        self[pid][STATE] = RUNNING

    def add_thread(self, func):                 # Thread list contains [Waitfor object, generator, pid, state]
        self.pid += 1                           # Run thread to first yield to acquire a Waitfor instance
        self.lstThread.append([func.send(None), func, self.pid, RUNNING]) # and put the resultant thread onto the threadlist
        return self.pid

    def run(self):                              # Run scheduler
        self._runthreads()

    def _idle_thread(self):                     # Runs once then in roundrobin or when there's nothing else to do
        if self.last_gc == 0 or microsSince(self.last_gc) > GCTIME:
            gc.collect()
            self.last_gc = pyb.micros()

    def triggered(self, thread):
        wf = thread[WAITFOR]
        if wf is None:
            return (0, 0, 0)                    # Roundrobin
        if isinstance(wf, Waitfor):
            return wf.triggered()
        raise ValueError('Thread yielded an invalid object')

    def _runthreads(self):                                  # Only returns if the stop method is used or all threads terminate
        self._idle_thread()
        while len(self.lstThread) and not self.bStop:       # Run until last thread terminates or the scheduler is stopped
            self.lstThread = [thread for thread in self.lstThread if thread[STATE] != DEAD] # Remove dead threads
            lstPriority = []                                # List threads which are ready to run
            lstRoundRobin = []                              # Low priority round robin threads
            for idx, thread in enumerate(self.lstThread):   # Put each pending thread on priority or round robin list
                priority = self.triggered(thread)           # (interrupt count, poll func value, uS overdue) or None
                if priority is not None:                    # Ignore threads waiting on events or time
                    if priority == (0,0,0) :                # (0,0,0) indicates round robin
                        lstRoundRobin.append(idx)
                    else:                                   # Thread is ready to run
                        lstPriority.append((priority, idx)) # List threads ready to run
            lstPriority.sort()                              # Lowest priority will be first in list

            done = False
            while not done:                                 # Until there are no round robin threads left
                while True:
                    lstrun = []
                    for ptuple in lstPriority:
                        idx = ptuple[1]
                        thread = self.lstThread[idx]
                        if thread[STATE] == RUNNING:
                            lstrun.append(lstPriority.index(ptuple))
#                    lstrun = [lstPriority.index(t) for t in lstPriority if self.lstThread[t[1]][STATE] == RUNNING]:  # Execute high priority threads first
                    if len(lstrun) == 0:
                        break
                    pidx = lstrun.pop(-1)
                    priority, idx = lstPriority.pop(pidx)     # Get highest priority thread. Thread:
                    thread = self.lstThread[idx]            # thread[0] is the current waitfor instance, thread[1] is the code
                    try:                                    # Run thread, send (interrupt count, poll func value, uS overdue)
                        thread[WAITFOR] = thread[FUNC].send(priority)  # Thread yields a Waitfor object or None store for subsequent testing
                    except StopIteration:                   # The thread has terminated:
                        self.lstThread[idx][STATE] = DEAD   # Flag thread for removal
                while not done:
                    setrun = set()
                    for idx in lstRoundRobin:
                        thread = self.lstThread[idx]
                        if thread[STATE] == RUNNING:
                            setrun.add(lstRoundRobin.index(idx))
#                    lstrun = [lstRoundRobin.index(t) for t in lstRoundRobin if self.lstThread[t][STATE] == RUNNING]:
                    if len(setrun) == 0:                 # There are no round robins pending. Quit the loop to rebuild new
                        self._idle_thread()
                        done = True
                        break                                   # lists of threads
                    idxrr = setrun.pop()
                    idx = lstRoundRobin.pop(idxrr)                   # Run an arbitrary round robin thread and remove from pending list
                    thread = self.lstThread[idx]
                    try:                                        # Run thread, send (0,0,0) because it's a round robin
                        thread[WAITFOR] = thread[FUNC].send((0,0,0))  # Thread yields a Waitfor object or None: store it
                    except StopIteration:                       # The thread has terminated:
                        self.lstThread[idx][STATE] = DEAD       # Flag thread for removal
                                                                # Rebuild priority list: time has elapsed and events may have occurred!
                    for idx, thread in enumerate(self.lstThread): # check and handle priority threads
                        priority = self.triggered(thread)       # (interrupt count, poll func value, uS overdue) or None
                                                                # Ignore pending threads, paused, scheduled for deletion and round robins
                        if priority is not None and priority != (0,0,0):
                            lstPriority.append((priority, idx)) # Just list threads wanting to run
                    lstPriority.sort()
