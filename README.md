# Micropython-scheduler

A set of libraries for writing threaded code on the MicroPython board. It has been tested on
Pyboards V1.0 and 1.1 and on the Pyboard Lite, also on ESP8266. It is incompatible with the WiPy
owing to its use of floats for time values. Drivers are included for switches, push-buttons and
alphanumeric LCD displays.

Owing to RAM constraints on the ESP8266 the main module usched.py must be implemented as frozen
bytecode.

Author: Peter Hinch
V1.08 23rd Sep 2016 Sets gc threshold in low priority thread. Checks add_thread() reentrancy.  
V1.07 11th Aug 2016. Thread status method added.  
V1.06 28th July 2016. Optional heartbeat LED on Pyboard and ESP8266.  
V1.05 19th May 2016. Uses utime for improved portability. See Porting below.  
API change: owing to utime's ``ticks_us()`` rollover the maximum time delay is reduced from 1073 to
536 seconds. For arbitrary delays use ``yield from wait()`` as before.

V1.04 27th Feb 2016. Now performs garbage collection to reduce heap fragmentation. Improved
scheduling algorithm. Threads can now pause, resume and kill other threads. Simplified usage.

# Introduction

Many embedded systems use cooperative multi tasking. A scheduler running concurrent threads
avoids much of the spaghetti code which can arise when servicing multiple physical devices.
The official way to achieve this is the ``uasyncio`` library.

This scheduler uses a well established Python technique known as microthreading or lightweight
threads. See [this paper from IBM](http://www.ibm.com/developerworks/library/l-pythrd/) for an old
introduction to the principle. This library was written before ``uasyncio`` existed and I believe
it still has relevance to those familiar with the thread paradigm. The following is a simple
example of its use, which flashes the four Pyboard LEDs in an asynchronous manner.

```python 
import pyb
from usched import Sched

def stop(ftim, objSch):                 # Stop the scheduler after ftim seconds
    yield ftim
    objSch.stop()

def toggle(objLED, period):             # Flash an LED periodically
    while True:
        yield period
        objLED.toggle()

leds = [pyb.LED(x) for x in range(1,5)] # Initialise all four on board LED's
objSched = Sched()                      # Instantiate the scheduler
for x in range(4):                      # Create a thread instance for each LED
    objSched.add_thread(toggle(leds[x], 0.2 + x/2))
objSched.add_thread(stop(10, objSched)) # Commit suicide after 10secs
objSched.run()                          # Run it!
```

For those new to asynchronous programming there is a brief introduction at the end of this
document.

### Files

There are five driver libraries. Items 2-5 inclusive use usched.
 1. usched.py The scheduler
 2. switch.py Support for debounced switches.
 3. pushbutton.py Supports callbacks on press, release, long click and double click.
 4. lcdthread.py Supports LCD displays using the Hitachi HD44780 controller chip.
 5. delay.py Classes and functions based on the scheduler: a simple retriggerable time delay class.
 A means of executing a callback at a future time.

Test/demonstration programs. The first two produce the most interesting demos :)
 1. ledflash.py Flashes the onboard LED's asynchronously.
 2. polltest.py A thread which blocks on a user defined polling function. Needs a board with an
 accelerometer.
 3. roundrobin.py Demonstrates round-robin scheduling.
 4. irqtest.py Demonstrates a thread which blocks on an interrupt (see code for wire links needed).
 5. subthread.py Illustrates dynamic creation and deletion of threads.
 6. lcdtest.py Demonstrates output to an attached LCD display.
 7. instrument.py The scheduler's timing functions employed to instrument code.
 8. pushbuttontest.py Demo of pushbutton class.
 9. pause.py Demo of threads controlling each other.
 10. cleanup.py Test of context managers in threads.
 11. syncom directory. A means of communication between boards running MicroPython independent of
 UARTs or other hardware. It enables the exchange of arbitrary Python objects. Tested between
 Pyboard and ESP8266. See [readme](./syncom/README.md).

# Usage

A typical program performs the following operations.
 1. Define the threads.
 2. Instantiate the scheduler.
 3. Assign to the scheduler threads which will run at start-up.
 4. Start the scheduler.

# Threads

A thread is written like a Python function except that it periodically yields to the scheduler (it
is a generator function). When it executes ``yield`` the scheduler may allocate time to another
thread before control returns to the statement following ``yield``. The thread ends when a
``return`` instruction is issued, or when the code runs out.

Threads can ``yield`` in the following ways which determine when the instruction after the
``yield`` statement is next run:
 1. ``yield`` (no argument). Thread runs in round-robin fashion.
 2. ``yield 0.2`` (A number). Thread delays for a time period in seconds.
 3. ``yield from wait(tim)`` As above, but handles arbitrarily long delays.
 4. ``yield obj`` (A ``Poller`` object). Thread waits on a user defined event.
 5. ``yield obj`` (A ``Pinblock`` object). Special class: thread waits on a pin state change.

These objects are described in detail below, along with two others which are supplied for
compatibility with existing code or specialist use.

# The Scheduler

This is defined by the ``Sched`` class. A program must create a single instance of the scheduler
with

```python
objSched = Sched()
```

Threads are assigned to the scheduler with the ``add_thread`` method. Note that the thread is
specified with function call syntax, with any required arguments being passed:

```python
objSched.add_thread(toggle(leds[x], 0.75))
```

The ``add_thread`` method may be issued from another thread, enabling threads to be dynamically
created. This should be done after at least one ``yield`` has been performed.

The ``Sched`` class  is started by calling its ``run()`` method: execution transfers to
the first thread to be scheduled. Any code following the call to ``run()`` will not be executed
until the scheduler terminates; up to that point execution is shared between the threads. The
scheduler will terminate either when all threads have terminated or when its ``stop()`` method
is called. Execution then continues with the line following the call to ``run()``.

When ``add_thread`` is issued the thread will run until the first yield statement. It will then
suspend execution until the scheduler starts. This enables initialisation code to be run in a well
defined order: the order in which threads are added. The ``add_thread`` method should not be called
in initialisation code.

If ``add_thread`` raises a ``StopIteration`` exception it is probably because your thread runs
to completion without executing ``yield``.

``add_thread`` returns an integer representing a unique ID for the thread. This may be used to
stop or pause the thread.

The scheduler constructor accepts two optional positional arguments:
 * ``gc_enable`` Default ``True``. If set ``False`` garbage collection is disabled: see below for
 an explanation of this.
 * ``heartbeat`` Default ``None``. Applies to Pyboard and esp8266. On the Pyboard, if an integer in
 range 1 to 4 is passed, the corresponding LED will flash when the scheduler is running. On the
 esp8266 any integer will cause the blue LED to flash (if fitted). Provides a visual check that no
 thread has hogged the Python VM by failing to yield or by invoking a blocking system call.

# Ways of Scheduling

When a thread yields, the scheduler returns information about the reason it was rescheduled.
In many cases this is ignored, but where it is required it is described in "Return from yield"
below.

### Round Robin scheduling

This causes the scheduler to reschedule the thread as soon as possible. If other threads are
pending round-robin scheduling they will be scheduled in turn before execution resumes. Higher
priority threads will be scheduled ahead of them. After running, a round-robin thread won't
run again until all other pending round-robin threads have run.

```python
def mythread():
    while True:
        # do stuff
        yield # round-robin is the default
```

The ``Roundrobin`` class is deprecated and exists for compatibility reasons only.

### Time delay scheduling

If a thread needs to wait, ideally it should do so by allowing other threads to run for the
duration of the delay. This is accomplished as follows:

```python
def mythread():
    while True:
        # do stuff
        yield 0.4 # 400ms delay
```

The scheduler will not resume until after the specified duration has elapsed. A thread which
has timed out takes precedence over round robin threads but the nature of cooperative multi-tasking
is that another thread may be running at the precise time that the timeout has elapsed: the
actual time of resumption may overrun, typically by a few milliseconds. Where delays in the
microsecond region are required, there is no alternative than to use the ``pyb.udelay()``
function.

The above syntax is valid for delays up to 536 seconds. For arbitrarily long delays issue

```python
def mythread():
    while True:
        # do stuff
        yield from wait(2000)
```

The amount of overrun may be retrieved as follows (see paragraph "Return from Yield" for
explanation).

```python
def mythread():
    while True:
        # do stuff
        result = yield 0.4  # 400ms delay
        overrun = result[2] # in us
```

The upper bounds on delays are explained above. The lower bound is zero but in practice periods
below a few milliseconds result in imprecise delays for the reason described. Further, repeatedly
issuing short delays may cause the thread to hog execution because timed-out threads have priority
over round robin ones.

### Wait on an Arbitrary Event

The ``Poller`` class allows a thread to wait on an arbitrary event, such as a character arriving on
a UART. The user provides a callback function which must return ``None`` unless the event has
occurred; in that case it should return an integer. This may optionally be retrieved by the thread:
see paragraph "Return from yield" below.

Typical code is as follows:

```python
wf = Poller(accel.poll, (4,), 2)   # Instantiate a Poller with 2 second timeout.
while True:
    reason = yield wf() # Reset timeout
    if reason[1]:    # Event has occurred, value is int returned by callback
        # code
    if reason[2]:    # It timed out. Value is no. of us it is late.
        # code
```

Arguments to the ``Poller`` constructor are:
 1. The callback function (which may be a class member).
 2. A tuple of arguments to the poll function (default () if none required).
 3. An optional timeout in seconds (default None: wait forever).

Yielding a ``Poller`` with function call syntax (as above) will reset the timeout to the value
specified in the constructor.

For performance reasons callback functions should be designed to execute quickly: the scheduler
runs the callback every time it allocates execution.

There is a potential trap in the use of Poller objects caused by the fact that polled threads have
priority over roundrobin ones. Consider:

```python
while True:
    do_something()
    yield my_poller_instance
```

This will monopolise the scheduler unless ``do_something()`` causes the poller at least sometimes
to yield ``False``. This may be avoided by adding a ``yield`` statement. This ensures that each
roundrobin thread runs before the routine runs again.

### Blocking on a Pin interrupt

The ``Pinblock`` class is for the somewhat specialist case where a pin is required to execute
an interrupt callback and subsequently schedule a thread. A typical use case is handling
a bit-banging communications protocol where the interrupt service routine (ISR) - which is called
very soon after the pin state change - puts data in a buffer which is then handled in slow time by
a thread. The thread will be scheduled as soon as possible after the ISR, but it's possible that
multiple ISR calls might occur before the thread is scheduled. It is possible to retrieve the
number of interrupts missed.

The example irqtest.py illustrates its use. The ``Pinblock`` constructor takes the following
arguments:
 1. A ``Pin`` object.
 2. The pin mode e.g. `` pyb.ExtInt.IRQ_FALLING``.
 3. The pin pull value e.g. ``pyb.Pin.PULL_NONE``.
 4. The interrupt callback function: takes one argument, the IRQ no.
 5. An optional timeout in seconds (default None: wait forever).

The return value enables the thread to determine whether the ``Pinblock`` timed out, and if
it did not, the number of interrupts which have occurred. Note that this count may be inaccurate
(low) if an interrupt occurred after the scheduler prioritised the thread but before it was
actually executed. In this instance the thread will be scheduled to run again.

Yielding a ``Pinblock`` with function call syntax will reset the timeout to the value
specified in the constructor.

Note that the interrupt callback function is run pre-emptively and precautions appropriate
to interrupt handlers are required. See the MicroPython documentation on
[interrupt handlers](http://docs.micropython.org/en/latest/reference/isr_rules.html).

### Return from yield

When a thread yields, the scheduler returns information about the reason it was re-started. In
many cases this may be ignored but where it is required it is accessed as follows:

```python
reason = yield wf() # wf is a Poller or Pinblock object
reason2 = yield 0.1 # retrieve overshoot
```

The data is a 3-tuple. It contains information about why the thread was scheduled. Elements are:
* elem[0] 0 unless thread returned a Pinblock and one or more interrupts have occurred, when it
 holds a count of interrupts.
* elem[1] 0 unless thread returned a Poller and the latter has returned an integer, when it holds
 that  value.
* elem[2] 0 unless thread was waiting on a timer or timeout when it holds no. of us it is late.

By implication if the thread yields nothing or a ``Roundrobin`` instance the return tuple will be
(0, 0, 0).

Where a timeout is provided to a ``Poller`` or ``Pinblock`` the value of item 2 enables the thread
to determine whether it was rescheduled because of the event or because of a timeout. A zero
value implies that the event occurred.

When a thread is added to the scheduler it runs until the first instance of ``yield``. The value
returned from that call to ``yield`` will be ``None``.

### Timeout class

If a thread yields a ``Timeout`` instance it will block for the duration of its time. In this
respect its behaviour is identical to ``yield from wait(time)`` and the latter should normally
be used. This is because it can handle arbitrarily long periods. The ``Timeout`` class is used
internally and documented as it may be of use in writing device drivers: instantiating a timeout
once and re-using it will offer some performance advantage.

The constructor takes a single argument ``tim`` being the delay in seconds. The maximum permitted
value is defined by ``MAXSECS`` and is 536 seconds. A ``TimerException`` will be raised if the
value exceeds this.

Yielding a ``Timeout`` with function call syntax will reset the timeout to the value specified
in the constructor.

Example code in irqtest.py and pushbutton.py.

# Thread control

The scheduler provides the following methods to enable threads to control each other. These
rely on the ``pid`` value returned by the ``add_thread`` method to identify the thread to be
controlled.  
``status`` Argument ``pid``. Returns 0 if thread is terminated, 1 if running, 2 if paused.  
``pause`` Argument ``pid``. Pauses the thread. A ``ValueError`` will be raised if the thread has
terminated.  
``resume`` Argument ``pid``. Resumes a paused thread. A ``ValueError`` will be raised if the thread
has terminated.  
``stop`` Optional argument ``pid``. Terminates a thread. A ``ValueError`` will be raised if the
thread has already terminated. If the argument is 0 or absent, the scheduler will be terminated.

Avoid writing a thread which waits for subthread to terminate by looping on its status: it's
usually more efficient to use ``yield from mythread()``.

# Threaded device drivers

These are provided for use in their own right and as examples of practical threaded code.

## Switch class

Provided by switch.py, sample code in irqtest.py

This simple class supports switch debouncing. Callbacks may be provided to run on switch closure,
switch opening or both. It assumes a set of contacts linking the pin to ground. The code fragment
below declares a switch on pin X5 which will run a callback called x5print with the argument
string "Red".

```python
Switch(objSched, 'X5', open_func = x5print, open_func_args = ("Red",))
```

Constructor arguments:
 1. The scheduler object.
 2. The pin name.
 3. Callback function to run on closure (or ``None``).
 4. Tuple of arguments for the closure callback (or ``()``- no arguments).
 5. Callback function to run on opening (or ``None``).
 6. Tuple of arguments for the opening callback (or ``()``).

## Pushbutton class

Provided by pushbutton.py, sample code in pushbuttontest.py.

This supports callbacks executed on button press, button release, double click, and long press.
Push-buttons may be linked to ground or vdd. The simplest introduction to the class is to view
the example code in pushbuttontest.py - note that the concepts of pressed or released are
independent of whether the button is wired to ground or vdd, and whether the contacts are
normally open or normally closed. A pushbutton object has a logical state ``True`` when pressed
that the driver abstracts from its physical state.

A typical code fragment is as follows:

```python
from pushbutton import Pushbutton, descriptor
  # Create threads and callback
objSched = Sched()
Pushbutton(objSched, 'X5', descriptor, false_func = x5print, false_func_args = ("Red",))
```

In this instance a function ``x5print`` is called with a single string argument 'Red' when the
button is released.

The characteristics of a ``Pushbutton`` are defined by a dictionary, and the driver provides a
typical instance ``descriptor``. The following keys must be present. Values in the ``descriptor``
object in brackets.

 1. ``no`` True if pushbutton contacts are normally open. (``True``).
 2. ``grounded`` True if button is wired to ground. (``True``).
 3. ``pull`` Value for ``Pin`` ``pull`` (``pyb.Pin.PULL_UP``).
 4. ``debounce`` Debounce time in seconds. (0.02).
 5. ``long_press_time`` Time to register a long press in secs (1).
 6. ``double_click_time`` Time to register a double click in secs (0.4).

The pushbutton constructor takes the following arguments (defaults in brackets):

 1. ``objSched`` The scheduler object (mandatory).
 2. ``pinName`` Pin name (e.g. 'X5') (mandatory).
 3. ``desc`` A descriptor dictionary (mandatory).
 4. ``true_func`` Callback on button press (``None``).
 5. ``true_func_args`` Tuple of arguments for above (``()``).
 6. ``false_func`` Callback on button release (``None``).
 7. ``false_func_args`` Tuple of arguments for above (``()``).
 8. ``long_func`` Callback on long press (``None``).
 9. ``long_func_args`` Tuple of arguments for above (``()``).
 10. ``double_func`` Callback on double click (``None``).
 11. ``double_func_args`` Tuple of arguments for above (``()``).

A ``Pushbutton`` object supports two methods.
 1. ``__call__`` Call syntax e.g. ``mybutton()`` returns the logical debounced state of the
 button.
 2. ``rawstate()`` Returns the logical instantaneous state of the button.

## LCD Class

Provided by lcdthread.py. Sample code in lcdtest.py.

This supports displays based on the Hitachi HD44780 controller chip and wired using four data
lines. It has been tested on 2 line x 16 character and 2 line x 24 character displays.

Pin definitions comprise a tuple comprising the names (e.g. 'Y1') of the following LCD pins:  
Rs, E, D4, D5, D6, D7  
The file provides a default tuple:  
PINLIST = ('Y1','Y2','Y6','Y5','Y4','Y3')

The LCD constructor takes the following arguments (defaults in brackets):
 1. ``pinlist`` A pinlist tuple as described above.
 2. ``scheduler`` The scheduler object.
 3. ``cols`` Number of display columns.
 4. ``rows`` Number of rows (2).

The LCD is addressed using array subscript notation, with the subscript denoting the row. You
should issue ``yield`` immediately after updating one or more rows.

```python
import pyb
from usched import Sched, wait
from lcdthread import LCD, PINLIST
def lcd_thread(mylcd):
    mylcd[0] = "MicroPython"
    yield
    while True:
        mylcd[1] = "{:11d}us".format(pyb.micros())
        yield 1

objSched = Sched()
lcd0 = LCD(PINLIST, objSched, cols = 16)
objSched.add_thread(lcd_thread(lcd0)) # Add any other threads and start the scheduler
```

## Delay Class

Provided by delay.py. Sample code in the pushbutton driver pushbutton.py.

This driver implements a software retriggerable monostable, akin to a watchdog timer. When first
instantiated a ``Delay`` object does nothing until its ``trigger`` method is called. It then enters
a running state until the specified time elapses when it calls the optional callback function and
stops running. A running ``Delay`` may be retriggered by calling its ``trigger`` method: its time
to run is now reset to the passed value. In other words, the callback will only be executed if the
``Delay`` times out before it is retriggered.

The usual caveats regarding microsheduler time periods applies: if you need millisecond accuracy
(or better) use a hardware timer. Times can overrun by 20ms or more, depending on other threads.
Further, though it behaves like a watchdog timer a hardware watchdog (as implemented on the
Pyboard) will trigger if the code crashes or hangs. The ``Delay`` object will not.

Constructor arguments:
 1. ``objSched`` The scheduler.
 2. ``callback`` The callback function (default ``None``).
 3. ``callback_args`` A tuple containing arguments for the callback (default ``()``).

Initially the object will do nothing until its ``trigger()`` method is called.

User methods:
 1. ``trigger`` argument ``duration``: callback will occur after ``duration`` seconds unless
 ``trigger`` is called again to reset the duration. Like feeding a watchdog.
 2. ``stop`` No argument. The callback will never occur unless ``trigger`` is called first.
 3. ``running`` No argument. Returns the running status of the object.

## future function

Provided by delay.py. A function which causes a user defined callback to be executed at a future
time.

Positional arguments:
 1. ``objSched`` Mandatory. The scheduler.
 2. ``time_to_run`` Mandatory. Number of seconds in the future when callback must run.
 3. ``callback``  Mandatory. The callback function or thread.
 4. ``callback_args`` A tuple of arguments for the callback. Default ``()`` (no args).

If ``callback`` is a thread it will be added to the scheduler when the time elapses. Thread
initialisation will commence at that time. The thread should be passed in the same way as a
callback function i.e. not using function call syntax:

```python
future(objsched, 30, my_thread, (thread_arg1, thread_arg2))
```

A ``TimerException`` will be raised if the time is not in the future (<= 0).

With judicious use of the ``utime`` library callbacks may be scheduled to run at specified absolute
(rather than relative) times.

# Implementation notes

### Timing

The scheduler's timing is based on pyb.micros(). The use of microsecond timing shouldn't lead the
user into hopeless optimism: if you want a delay of 1ms exactly don't issue ``yield 0.001``
and expect to get a one millisecond delay. It's a cooperative scheduler. Another thread will be
running when the period elapses. Until that thread decides to yield your thread has no chance of
restarting. Even then a higher priority thread such as one blocked on an interrupt may, by then, be
pending. So, while the minimum delay will be 1ms, the maximum is dependent on the other code you
have running. On the Pyboard board don't be too surprised to see delays of many milliseconds.

If you want precise non-blocking timing, especially at millisecond level or better, use one of the
hardware timers.

Avoid issuing short timeout values. A thread which does so will tend to hog execution at the
expense of other threads. The well mannered way to yield control in the expectation of restarting
soon is to simply issue ``yield``. Such a thread will resume when other round-robin threads
(and higher priority threads such as expiring delays) have been scheduled.

### Garbage collection

When an object is instantiated MicroPython allocates RAM from a pool known as the heap. After a
program has run for some time the heap will become cluttered with objects which have gone out of
scope. Eventually this will cause an allocation to fail. MicroPython then goes through a process of
garbage collection (GC) in which unused objects are deleted. The allocation is then attempted
again. GC can take many ms and, from the point of view of the program, it occurs at random
intervals.

The scheduler attempts to improve on this. It is beneficial to perform garbage collection regularly.
This has two advantages. Firstly the time taken by GC is much reduced: typically 1ms. Secondly it
reduces heap fragmentation which improves program performance. It can also improve reliability: a
badly fragmented heap can cause irretrievable allocation failures.

The scheduler has a built-in thread ``_idle_thread`` which is scheduled on a round robin basis. This
performs a GC if it hasn't been done for an interval defined by ``Sched.GCTIME`` (current 50ms).
Garbage collection can be disabled by passing ``gc_enable = False`` to the scheduler constructor.

### Pinblock objects and interrupts

The way in which the scheduler supports pin interrupts is described in irqtest.py. In essence the
user supplies a callback function. When an interrupt occurs, the default callback runs which
increments a counter and runs the user's callback. A thread which yielded a ``Pinblock`` and
blocked on this interrupt will be rescheduled by virtue of the scheduler checking this counter.
Such threads have the highest priority.

### Priorities

The paragraph "Return from yield" above describes the 3-tuple returned by the scheduler when a thread
is scheduled. The natural sort order of such tuples defines the priorities used to determine the order
in which pending threads are run, vis:

 1. ``Pinblock`` threads in order of decreasing interrupts missed.
 2. ``Poller`` threads where the event has occurred in decreasing order of integer returned.
 3. Time delays: most overdue first.
 4. Round-robin threads.

The execution order of round-robin threads is not guaranteed, except that when one runs each
other round-robin thread will run before the first runs again.

# Hints and tips

### Program hangs and errors

Hanging almost always happens because a thread has blocked without yielding: this will hang the
entire system. A common cause of exceptions is to ``yield`` something other than the objects
detailed above.

### Instrumenting your code

The following thread is useful in testing programs. It terminates the test (and optionally
terminates the scheduler) after a given number of seconds and prints the maximum overrun on a
timed thread which occurred in that period. This gives an indication of how long your other
threads are blocking the execution of the scheduler.

```python
def instrument(objSched=None, interval=0.1, duration=10):
    if interval == 0 or interval > duration:
        raise ValueError('Arguments are invalid')
    count = duration // interval
    max_overrun = 0
    while count:
        count -= 1
        result = yield interval
        max_overrun = max(max_overrun, result[2])
    print('Maximum overrun = {}us'.format(max_overrun))
    if objSched is not None:
        objSched.stop()
```

As a general guide, in trivial programs such as ledflash.py a ``yield interval`` can be
expected to overrun by just over 2ms maximum.

# Notes for beginners

### Why scheduling?

Using a scheduler doesn't enable anything that can't be done with conventional code. But it does
make the solution of certain types of problem simpler to code and easier to read and maintain.

It facilitates a style of programming based on the concept of routines offering the illusion of
running concurrently. This can simplify the process of interacting with physical devices.
Consider the task of reading 12 push-buttons. Mechanical switches such as buttons suffer from
contact bounce. This means that several rapidly repeating transitions can occur when the button
is pushed or released. The simplest way to eliminate this is, on receipt of the first transition,
to wait (typically 20ms) and check the state of the button. By then the bouncing will be over
and its state can be read. Doing this in linear code for 12 buttons can get messy. So we write

```python
def cb(button_no):  # user code omitted. This runs when
                    # button pressed, with the button number passed

buttons = ('X1', 'X2', 'X3', 'X4', 'X5', 'X6', 'X7', 'X8', 'X9', 'X10', 'X11', 'X12')
objSched = Sched()
for button_no, button in enumerate(buttons):
    Pushbutton(objSched, button, descriptor, true_func = cb, true_func_args = (button_no,))
objSched.run()
```

The ``Pushbutton`` constructor hides the detail, but for each button it creates a thread which
performs the debouncing. It can also start briefly-running threads to check for long presses
and double clicks. Both the driver and the above code sample are written using an event driven
model, as used in graphical user interfaces and many embedded systems.

Scheduling also solves the problem of blocking. If some code needs to wait for a physical event
to occur before it can continue it is said to be blocked. You may not want the entire system to
be blocked. While this can be solved in conventional code, in threaded code the solution is
trivial. The thread blocks, but while it does so it periodically yields execution. Hence the rest
of the system continues to run.

### Why cooperative?

The initial reaction to the idea of cooperative multi-tasking tends to be one of disappointment.
Surely pre-emptive is better? The answer, when it comes to embedded systems, is usually no. To make
a case for the defence a pre-emptive model has one advantage: if someone writes

```python
for x in range(1000000):
    # do something time consuming
```

it won't lock out other threads, whereas without a ``yield`` statement it will lock a cooperative
scheduler solid.

Alas this benefit pales into insignificance compared to the drawbacks. Some of these are covered in
the documentation on writing [interrupt handlers](http://docs.micropython.org/en/latest/reference/isr_rules.html).
In a pre-emptive model every thread can interrupt every other thread. It is generally much easier
to find and fix a lockup resulting from a thread which fails to ``yield`` than locating the
sometimes deeply subtle bugs which can occur in pre-emptive code.

To put this in simple terms, if you write a thread in MicroPython, you can be sure that variables
won't suddenly be changed by another thread: your thread has complete control until it issues
``yield``. Unless, of course, you have written an interrupt handler; these are pre-emptive.

There is also the issue of performance: the context switching involved in pre-emption is
computationally demanding. It is also hard to implement and beyond the scope of Python. Lightweight
threads allow for simple context switching; this scheduler employs conventional Python code.

### Communication

In non-trivial applications threads need to communicate. Conventional Python techniques can be
employed. These include the use of global variables or declaring threads as object methods which
can then share instance variables. Alternatively a mutable object may be passed as a thread
argument. Pre-emptive systems usually mandate specialist classes to achieve "thread safe"
communications; in a cooperative system these are seldom required.

### Polling

Some hardware devices such as the accelerometer don't support interrupts, and therefore must be
polled. One option suitable for slow devices is to write a thread which polls the device
periodically. A faster and more elegant way is to delegate this activity to the scheduler. The
thread then suspends execution of that thread pending the result of a user supplied callback
function, which is run by the scheduler. From the thread's point of view it blocks pending an
event - with an optional timeout available. See paragraph "Wait on an Arbitrary Event" above.

# Porting

usched.py uses standard MicroPython syntax and libraries with one exception: the ``Pinblock``
class. This is Pyboard specific in its use of interrupts. If the target doesn't support the pyb
library the ``Pinblock`` class should be ignored, deleted or adapted.
