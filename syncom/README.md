# Communication between MicroPython hardware boards

This provides a means of communication between two devices, each running MicroPython, where a UART
cannot be used. An example is where one device is an ESP8266 board. While this has one
bidirectional UART, this may be in use either as a REPL console, for viewing debug output, or for
other puposes.

It is intended for use in asynchronous programs. Currently it uses usched as a framework for
cooperative multi-tasking.

The module offers a bidirectional full duplex communication channel between two hardware devices.
Its unit of communication is an arbitrary Python object making for simple application. Physically
it uses a 4-wire interface. It is designed to run on devices with minimal features and makes no
assumptions about processing performance: at a physical level the interface is synchronous. If each
device has two pins which can be used for output and two for input, and is capable of running the
scheduler it should work.

Now supports a timeout to enable the detection and resetting of a crashed target device.

## Example usage

```python
from usched import Sched
from syncom import SynCom
from machine import Pin

 # Thread just echoes objects back
def my_thread(chan):
    yield
    while True:
        yield chan.await_obj    # Wait for input
        obj = chan.get()        # Receive an object
        chan.send(obj)          # send it back

mtx = Pin(14, Pin.OUT)          # Define pins
mckout = Pin(15, Pin.OUT, value = 0) # clock must be initialised to zero.
mrx = Pin(13, Pin.IN)
mckin = Pin(12, Pin.IN)

objsched = Sched()              # Instantiate scheduler
channel = SynCom(objsched, True, mckin, mckout, mrx, mtx)
channel.start()
objsched.add_thread(my_thread(channel))
try:
    objsched.run()
finally:                        # Under test conditions where code fails or
    mckout(0)                   # is interrupted, set up hardware for a re-run
```

## Advantages

 * Readily portable to any MicroPython platform.
 * It does not use hardware features such as interrupts or timers.
 * Hardware requirement: two arbitrary output pins and two input pins on each device.
 * The interface is synchronous, having no timing dependencies.
 * It supports full duplex communications (concurrent send and receive).
 * The unit of transmission is an arbitrary Python object.
 * All methods are non-blocking.
 * Small: ~130 lines of Python.

## Limitations

 * The interface is an alternative to I2C or SPI and is intended for directly linked devices
 sharing a common power supply.
 * It is slow. With a Pyboard linked to an ESP8266 clocked at 80MHz, throughput is about 1.8Kbps.
 In practice throughput will depend on the performance of the slowest device and the behaviour of
 other threads. Clocking the ESP8266 at 160MHz yields about 3.2Kbps, a 75% improvement. Note these
 figures represent raw bps figures: mean throughput will be lower, see section Timing below.

## Rationale

The obvious question is why not use I2C or SPI. The reason is the nature of the slave interfaces:
these protocols are designed for the case where the slave is a hardware device which guarantees a
timely response. The MicroPython slave drivers achieve this by means of blocking system calls.
Such calls are incompatible with asynchronous programming.

The two ends of the link are defined as ``initiator`` and ``passive``. These describe their roles
in initialisation. Once running the protocol is symmetrical and the choice as to which unit to
assign to each role is arbitrary.

# Files

 * syncom.py The library.
 * sr_init.py Test program configured for Pyboard: run with sr_passive.py on other device.
 * sr_passive.py Test program configured for ESP8266: sr_init.py runs on other end of link.

# Hardware connections

Each device has the following logical connections, ``din``, ``dout``, ``ckin``, ``ckout``. The
``din`` (data in) of one device is linked to ``dout`` (data out) of the other, and vice versa.
Likewise the clock signals ``ckin`` and ``ckout``. To ensure reliable startup the clock signals
should be pulled down with 10K resistors. The Pyboard's internal pulldown is not suitable. This is
because after reset, Pyboard pins are high impedance. If the other end of the link starts first, it
will see a floating input. It is best to avoid using pin 15 as an input as it is used to detect
boot mode. On the reference board it has a 10K pull-down so using it as the ``ckout`` pin is
permissible and saves the need for an external resistor.

| Initiator   | Passive     |
|:-----------:|:-----------:|
| dout  (o/p) | din   (i/p) |
| din   (i/p) | dout  (o/p) |
| ckout (o/p) | ckin  (i/p) |
| ckin  (i/p) | ckout (o/p) |

An additional optional connection may be provided to enable one device to reset the other. For
example a Pyboard linked to an ESP8266 might reset the ESP8266 in the event of a timeout. The
watchdog timer on the Pyboard could extend this capability, restarting the Pyboard and in turn
resetting the ESP8266 in the event of a fault. A reset connection simplifies development in that
restarting the Pyboard code can reset the ESP8266 enabling automatic synchronisation.

In this instance the pin providing the reset is arbitrary, but must be connected to the reset pin
of the target. The polarity of the reset pulse is definable in code (0 is required by the ESP8266).

# The library

This has the following dependencies.

[pickle.py](https://github.com/micropython/micropython-lib/tree/master/pickle)  
[usched.py](https://github.com/peterhinch/Micropython-scheduler.git)

# class SynCom

## Constructor

Positional arguments:

 1. ``objsched`` The scheduler instance.
 2. ``passive`` Boolean. One end of the link sets this ``True``, the other ``False``.
 3. ``ckin`` An initialised input ``Pin`` instance.
 4. ``ckout`` An initialised output ``Pin`` instance. It should be set to zero.
 5. ``din`` An initialised input ``Pin`` instance.
 6. ``dout`` An initialised output ``Pin`` instance.
 7. ``latency`` (optional) default 5. Sets the number of characters exchanged before yielding to
 the scheduler.
 8. ``verbose`` (optional) default ``True``. If set, synchronisation messages will be output to the
 REPL.

## Methods

 * ``start`` Optional args a ``Pin`` instance and an integer (0 or 1) a reset state. Starts or
 restarts the interface. The arguments provide for resetting the remote hardware, for example if a
 failure occurs. The passed pin is driven to the passed value for 100ms.
 * ``send`` Argument an arbitrary Python object. Sends it to the receiving hardware.
 * ``send_str`` Argument a string. Sends it to the receiving hardware.
 * ``get`` Return a received Python object if one exists and remove it from the queue, otherwise
 return ``None``.
 * ``get_str`` Return a string if one exists and remove it from the queue, otherwise return
 ``None``.
 * ``any`` Return the number of received objects in the queue.
 * ``set_timeout`` Optional argument an integer no. of us. Returns the current timeout
 value. The timeout provides for the case where the remote device crashes, is reset or
 calls a method which blocks indefintely: this will cause the scheduler on the local unit
 to pause for the timeout duration as it waits for the remote. The initial timeout value
 is 0 signifying no timeout. ``set_timeout`` can be called before issuing ``start``.
 * ``running`` No args. Returns ``True`` if it's started and running. Will return ``False`` if
 it has timed out.

## Attributes

 * ``await_obj`` This is an instnce of a scheduler ``Poller`` class. The following code fragment
 illustrates its use in waiting for an incoming object:

```python
    while True:
        reason = yield channel.await_obj  # Thread pauses here
        if reason[1] == 1:
            obj = channel.get()
        elif reason[1] == 2:
            raise MyException # Handle crashed target
        # process obj
```

It returns 1 if an incoming object has been received, 2 if the link has timed out.

# Notes

## Synchronisation

When a unit issues the ``start`` method a thread is started which runs forever. If a reset pin
argument is provided it resets the other unit, otherwise the assumption is that both units have
started after power has been applied. The units achieve synchronisation when each has received a
known sync character from the other. The link then runs continuously as a background process. In
normal circumstances synchronisation is maintained indefinitely, the exception being if one end of
the link suffers a software crash.

If a system is to be capable of surviving this, the unit which is still running needs to be able to
detect the failure. Its SynCom object will time out and its ``running`` method will return ``False``.
By polling this another thread can restart its own interface and reset the failed unit. It should do
this by issuing ``start`` with reset arguments (pin and state). This resets the other unit, kills
its own backround thread and then restarts it, so the synchronisation phase begins again.

## send_str and get_str methods

On resource constrained platforms the pickle module can be problematic: the method used to convert
a string to an arbitrary Python object involves invoking the compiler which demands significant
amounts of RAM. This can be avoided by sending only strings to the resource constrained platform,
which must then parse the strings as required by the application. The protocol places some
restrictions. The bytes must not include 0, and they are limited to 7 bits. The latter limitation
can be removed (with small performance penalty) by changing the value of ``_BITS_PER_CH`` to 8.
The limitations allow for normal UTF8 strings.

Note that on resource constrained platforms sending arbitrary Python objects should not be an issue
as the relevant pickle method uses only ``repr``.

## Latency

The time taken to transmit a character is approximately 4ms (assuming a Pyboard linked to an
ESP8266). Yielding to the scheduler after such a brief interval would result in excessive task
switching; the ``latency`` value provides control over the length of time the background thread
monopolises the processors of both devices and is defined as the number of characters exchanged
between ``yield`` statements. The default provides for a time of around 20ms.

## Timing

The timing measurements in Limitations above were performed as follows. A logic analyser was
connected to one of the clock signals and the time for one character (7 bits) to be transferred was
measured (note that a bit is transferred on each edge of the clock). This produced figures for the
raw bits per second throughput of the bitbanged interface.

The value produced by the test programs (sr_init.py and sr_passive.py) is the total time to send an
object and receive it having been echoed back by the ESP8266. This includes encoding the object as
a string, transmitting it, decoding and modifying it, followed by similar processing to send it
back. Hence converting the figures to bps will produce a lower figure (on the order of 1.3Kbps at
160MHz).

## The Pickle module

The library uses the Python pickle module for object serialisation. This has some restrictions,
notably on the serialisation of user defined class instances. See the Python documentation.
Currently there is a MicroPython issue #2280 where a memory leak occurs if you pass a string
which varies regularly. Pickle saves a copy of the string (if it hasn't already occurred) each time
until RAM is exhausted. The workround is to use any data type other than strings or bytes objects.
