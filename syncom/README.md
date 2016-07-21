# Communication between MicroPython hardware boards

This is intended for a somewhat specialised situation where two devices, each running MicroPython,
need to communicate and a UART cannot be used. An example is where one end of the link is an
ESP8266 board. While this has one bidirectional UART, this may be in use either as a REPL console
or for other puposes.

It is intended for use in asynchronous programs. Currently it uses usched. When (u)asyncio develops
to the extent that it can work fast enough, I will produce a port.

The module offers a bidirectional full duplex communication channel between two hardware devices.
Its unit of communication is an arbitrary Python object making for simple application. Physically
it uses a 4-wire interface. It is designed to run on devices with minimal features and makes no
assumptions about processing performance. If each device has two pins which can be used for output,
and two for input, it should work.

## Example usage

```python
from usched import Sched
from syncom import SynCom
from machine import Pin

 # Thread just echoes objects back
def my_thread(chan):
    yield
    while True:
        while not chan.any():   # Wait for input
            yield
        obj = chan.get()        # Receive an object
        chan.send(obj)          # send it back

mtx = Pin(14, Pin.OUT)          # Define pins
mckout = Pin(15, Pin.OUT, value = 0) # clock must be initialised to zero.
mrx = Pin(13, Pin.IN)
mckin = Pin(12, Pin.IN)

objsched = Sched()              # Instantiate scheduler
channel = SynCom(objsched, True, mckin, mckout, mrx, mtx)
objsched.add_thread(my_thread(channel))
try:
    objsched.run()
finally:                        # Under test conditions where code fails or
    mckout(0)                   # is interrupted, set up hardware for a re-run
```

## Advantages

 * It should be portable to any MicroPython platform.
 * It does not use hardware features such as interrupts or timers.
 * Hardware requirement: two arbitrary output pins and two input pins on each device.
 * The interface is synchronous, having no timing dependencies.
 * It supports full duplex communications (concurrent send and receive).
 * The unit of transmission is an arbitrary Python object.
 * All methods are non-blocking.

## Limitations

 * The interface is an alternative to I2C or SPI and is intended for directly linked devices
 sharing a common power supply.
 * It is slow. With a Pyboard linked to an ESP8266, throughput is about 1.6Kbps. In practice
 throughput will depend on the performance of the slowest device and the behaviour of other
 threads.

## Rationale

The obvious question is why not use I2C or SPI. The reason is the nature of the slave interfaces:
these protocols are designed for the case where the slave is a hardware devices which guarantees a
timely response. The MicroPython slave drivers achieve this by means of blocking system calls.
Such calls are incompatible with asynchronous programming.

The two ends of the link are defined as ``initiator`` and ``passive``. These describe their roles
in initialisation. From a user perspective the protocol is symmetrical.

# Files

 * syncom.py The library.
 * sr_init.py Test program configured for Pyboard: run with sr_passive.py on other device.
 * sr_passive.py Test program configured for ESP8266: sr_init.py runs on other end of link.

# Hardware connections

Each device has the following logical connections, din, dout, ckin, ckout. The din (data in) of one
device is linked to dout (data out) of the other, and vice versa. Likewise the clock signals ckin
and ckout. To ensure reliable startup the clock signals should be pulled down with 10K resistors.
The Pyboard's internal pulldown is not suitable. This is because after reset, Pyboard pins are high
impedance. If the other end of the link starts first, it will see a floating input. The reference
Adafruit Feather Huzzah board has a 10K pulldown on pin 15.

| Initiator   | Passive     |
|:-----------:|:-----------:|
| dout  (o/p) | din   (i/p) |
| din   (i/p) | dout  (o/p) |
| ckout (o/p) | ckin  (i/p) |
| ckin  (i/p) | ckout (o/p) |

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

 * ``send`` Argument an arbitrary Python object. Sends it to the receiving hardware.
 * ``get`` Return a received Python object if one exists and remove it from the queue, otherwise
 return ``None``.
 * ``any`` Return the number of received objects in the queue.

# Notes

The library uses the Python pickle module for object serialisation. This has some restrictions,
notably on the serialisation of user defined class instances. See the Python documentation.

I have encountered situations where the test program running on the ESP8266 fails to acquire sync.
The reason for this is unclear but a soft reset clears the problem. If run from main.py it starts
correctly from power up.

