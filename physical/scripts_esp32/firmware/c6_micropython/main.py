"""Device 05: legitimate CoAP/Wi-Fi gateway, MicroPython ESP32-C6.

Independent acquisition implementation; the four S3 Arduino clients are unchanged.
No attacks, spoofing or forwarding. Timing targets and actual counters are logged.
"""
import gc
import json
import network
import os
import select
import socket
import sys
import time
from coap_wire import request, decode, validate_response
from config_local import SSID, PASSWORD, SERVER


def emit(event, **values):
    values.update(event=event, device=5, ms=time.ticks_ms())
    print(json.dumps(values))


class Client:
    def __init__(self):
        self.wifi = network.WLAN(network.WLAN.IF_STA)
        self.wifi.active(True)
        self.wifi.config(pm=network.WLAN.PM_NONE)
        self.wifi.connect(SSID, PASSWORD)
        self.sock = None
        self.pending = {}
        self.mid = int.from_bytes(os.urandom(2), "big")
        self.token = int.from_bytes(os.urandom(4), "big")
        self.random_state = 2026 ^ (0x9e3779b9 * 5 & 0xffffffff)
        self.stats = dict(sent=0, received=0, timeouts=0, invalid=0, send_failed=0,
                          capacity_skipped=0, scheduler_skipped=0, transfers=0, cancelled=0)
        self.active = True
        self.kind = None
        self.transfer = None
        self.retry_at = self.summary_at = self.expire_at = 0
        self.input = ""
        self.poll = select.poll()
        self.poll.register(sys.stdin, select.POLLIN)

    def random(self, minimum, maximum):
        value = self.random_state
        value ^= value << 13 & 0xffffffff
        value ^= value >> 17
        value ^= value << 5 & 0xffffffff
        self.random_state = value & 0xffffffff
        return minimum + self.random_state % (maximum - minimum + 1)

    def new_token(self):
        self.token = (self.token + 1) & 0xffffffff
        return self.token.to_bytes(4, "big")

    def send(self, now, block=None, download=False):
        if len(self.pending) >= 64:
            self.stats["capacity_skipped"] += 1
            return
        token = self.transfer["token"] if download else self.new_token()
        if token in self.pending:
            self.stats["capacity_skipped"] += 1
            return
        self.mid = (self.mid + 1) & 65535
        packet = request(self.mid, token, "large" if block is not None else "sensor", block, download)
        try:
            if self.sock.sendto(packet, (SERVER, 5683)) != len(packet):
                raise OSError("Incomplete datagram")
        except OSError:
            self.stats["send_failed"] += 1
            return
        self.pending[token] = (now, self.mid, block, download)
        self.stats["sent"] += 1

    def receive(self):
        for _ in range(32):
            try:
                packet, origin = self.sock.recvfrom(1200)
            except OSError:
                break
            if origin != (SERVER, 5683):
                self.stats["invalid"] += 1
                continue
            try:
                result = decode(packet)
                entry = self.pending.get(result["token"])
                if entry is None:
                    raise ValueError("Unmatched token")
                _, mid, block, download = entry
                validate_response(result, mid, block, download)
                if download and self.transfer is not None and result["token"] == self.transfer["token"]:
                    if self.transfer["etag"] not in (None, result["etag"]):
                        raise ValueError("ETag changed during transfer")
                    self.transfer["etag"] = result["etag"]
                    self.transfer["next"] += 1
                    if self.transfer["next"] == 32:
                        self.stats["transfers"] += 1
                        self.transfer = None
                del self.pending[result["token"]]
                self.stats["received"] += 1
            except (ValueError, IndexError):
                self.stats["invalid"] += 1

    def summary(self):
        emit("summary", active=self.active, connected=self.wifi.isconnected(),
             ip=self.wifi.ifconfig()[0], pending=len(self.pending), heap_free=gc.mem_free(), **self.stats)

    def commands(self):
        for _ in range(32):
            if not self.poll.poll(0):
                break
            char = sys.stdin.read(1)
            if char in ("\r", "\n"):
                if self.input == "STATUS":
                    self.summary()
                elif self.input == "STOP":
                    self.active = False
                    self.kind = self.transfer = None
                    emit("manual_stop")
                elif self.input == "START":
                    self.active = True
                    emit("manual_start")
                self.input = ""
            elif len(self.input) < 16:
                self.input += char

    def loop(self):
        now = time.ticks_ms()
        self.commands()
        if not self.wifi.isconnected():
            if self.sock is not None:
                self.sock.close(); self.sock = None
                self.stats["cancelled"] += len(self.pending)
                self.pending.clear(); self.kind = self.transfer = None
                emit("wifi_disconnected")
            if time.ticks_diff(now, self.retry_at) >= 0:
                try:
                    self.wifi.connect(SSID, PASSWORD)
                except OSError:
                    pass
                self.retry_at = time.ticks_add(now, 15000)
            time.sleep_ms(10)
            return
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("0.0.0.0", 56835)); self.sock.setblocking(False)
            self.sensor_at = time.ticks_add(now, 5000)
            self.fast_at = time.ticks_add(now, self.random(8000, 20000))
            emit("ready", profile=5, ip=self.wifi.ifconfig()[0],
                 mac=":".join("%02x" % n for n in self.wifi.config("mac")),
                 local_port=56835, runtime=sys.version)
        self.receive()
        if time.ticks_diff(now, self.expire_at) >= 0:
            for token, entry in list(self.pending.items()):
                if time.ticks_diff(now, entry[0]) >= 3000:
                    del self.pending[token]; self.stats["timeouts"] += 1
                    if self.transfer is not None and token == self.transfer["token"]:
                        self.transfer = None
            self.expire_at = time.ticks_add(now, 100)
        if time.ticks_diff(now, self.summary_at) >= 0:
            self.summary(); self.summary_at = time.ticks_add(now, 5000)
        if not self.active:
            time.sleep_ms(2)
            return
        if time.ticks_diff(now, self.sensor_at) >= 0:
            self.send(now)
            self.sensor_at = time.ticks_add(now, self.random(500, 700))
        if self.kind is not None and time.ticks_diff(now, self.fast_end) >= 0:
            emit("fast_end", kind=self.kind, sent=self.stats["sent"] - self.fast_sent)
            self.kind = self.transfer = None
            self.fast_at = time.ticks_add(now, self.random(8000, 20000))
        if self.kind is None and time.ticks_diff(now, self.fast_at) >= 0:
            self.kind = ("sensor", "reads", "download")[self.random(0, 2)]
            rates = (40, 80, 150, 250) if self.kind == "sensor" else (20, 50, 100, 200)
            rate = rates[self.random(0, 3)]
            duration = self.random(2000, 5000)
            self.fast_end = time.ticks_add(now, duration)
            self.fast_next = now
            self.fast_interval = max(1, round(1000 / rate))
            self.fast_sent = self.stats["sent"]
            self.fixed_block = self.random(0, 31)
            emit("fast_start", kind=self.kind, target_rps=rate, duration_ms=duration)
        if self.kind is not None and time.ticks_diff(now, self.fast_next) >= 0:
            if self.kind == "download":
                if self.transfer is None:
                    self.transfer = dict(token=self.new_token(), next=0, etag=None)
                self.send(now, self.transfer["next"], True)
            else:
                self.send(now, self.fixed_block if self.kind == "reads" else None)
            overdue = max(0, time.ticks_diff(now, self.fast_next))
            self.stats["scheduler_skipped"] += overdue // self.fast_interval
            self.fast_next = time.ticks_add(now, self.fast_interval)
        time.sleep_ms(1)


client = Client()
while True:
    client.loop()
