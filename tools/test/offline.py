"""Loopback-only namespace init; reap orphaned grandchildren during tests."""
import ctypes
import fcntl
import json
import subprocess
import os
import signal
import socket
import struct
import sys
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    name = struct.pack('16sH14s',b'lo',0,b'')
    flags = fcntl.ioctl(sock.fileno(),0x8913,name)
    current = struct.unpack('16sH14s',flags)[1]
    fcntl.ioctl(sock.fileno(),0x8914,struct.pack('16sH14s',b'lo',current | 1,b''))
for dependency in json.loads(os.environ.get('RESEARCH_AGENT_TEST_DEPENDENCIES','[]')):
    subprocess.run(['/usr/bin/mount','--bind',dependency,dependency],check=True)
    subprocess.run(['/usr/bin/mount','-o','remount,bind,ro',dependency],check=True)
if ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)!=0:
    raise OSError('Test namespace init cannot adopt orphaned children')
child=os.fork()
if child==0:
    os.setsid()
    os.execvpe(sys.argv[1],sys.argv[1:],os.environ)

def forward(signum,frame):
    try: os.killpg(child,signum)
    except ProcessLookupError: pass

for signum in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP): signal.signal(signum,forward)
while True:
    pid,status=os.waitpid(-1,0)
    if pid==child:
        raise SystemExit(os.waitstatus_to_exitcode(status))
