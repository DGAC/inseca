# This file is part of INSECA.
#
#    Copyright (C) 2020-2022 INSECA authors
#
#    INSECA is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    INSECA is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License

import datetime
import os
import sys
import subprocess
import select
import time
import signal
import Utils as util

class DDTool:
    def __init__(self, devfile, input_file=None):
        """If input file is not defined, then /dev/zero is used."""
        # process
        self._process=None
        self._select=None

        self._devname=devfile

        if input_file:
            self._input_file=input_file
            self._size=os.stat(input_file).st_size
        else:
            self._input_file="/dev/zero"
            util.get_disk_sizes(self._devname)[0]

        # reporting
        self._percent=0
        self._started_ts=None

    def __del__(self):
        if self._process!=None:
            if self._process.poll()==None:
                self._process.kill()
                self._process.wait(5)

    def write(self):
        started=int(datetime.datetime.now().strftime("%s"))

        # data writing
        self._write_start()
        while True:
            time.sleep(1)
            (percent, remain)=self._write_progress()
            if not sys.stdout.isatty():
                if remain:
                    msg="%s"%util.delay_to_text(remain)
                else:
                    msg="N/A"
                if util.debug:
                    print(msg)
            if percent>=100:
                break

        # return write delay
        finished=int(datetime.datetime.now().strftime("%s"))
        return finished-started

    def _write_start(self):
        if self._process!=None:
            raise Exception("CODEBUG: writing already in process")
        args=["dd", "if=%s"%self._input_file, "bs=4M", "of=%s"%self._devname, "oflag=dsync"]
        self._process=subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self._select=select.poll()
        self._select.register(self._process.stdout, select.POLLIN)
        self._started_ts=int(datetime.datetime.now().strftime("%s"))

    def _write_progress(self):
        """Returns:
        - the percentage done
        - the estimated number of seconds remaining
        """
        if self._process==None:
            raise Exception("CODEBUG: wiping hs not been requested")
        if self._process.poll()!=None:
            self._process=None
            return (100, 0)

        self._process.send_signal(signal.SIGUSR1)
        process=self._percent
        while self._select.poll(1):
            line=self._process.stdout.readline()
            line=line.decode()
            if " bytes " in line:
                parts=line.split(" ")
                nbytes=int(parts[0])
                process=nbytes*100/self._size
                self._percent=int(process)
                if self._percent>100:
                    self._percent=100
                    process=100
        ellapsed=int(datetime.datetime.now().strftime("%s"))-self._started_ts

        if self._percent<2:
            remain=None
        else:
            estimated=ellapsed*100/process
            if process<10:
                estimated=estimated*(1+(10-process)/10)
            remain=estimated-ellapsed
        return (self._percent, remain)
