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

import os
import psutil

class AlreadyRunningError(Exception):
    pass

class PIDProtector(object):
    def __init__(self, filename):
        self._process_name = psutil.Process(os.getpid()).cmdline()[0]
        filename=os.path.realpath(filename)
        os.makedirs(os.path.dirname(filename), mode=0o700, exist_ok=True)
        self._file = filename

    def is_running(self):
        if not os.path.exists(self._file):
            return False

        with open(self._file, "r") as f:
            try:
                pid = int(f.read())
            except (OSError, ValueError):
                return False

        if not psutil.pid_exists(pid):
            return False

        try:
            cmd1=psutil.Process(pid).cmdline()[0]
            return cmd1==self._process_name
        except psutil.AccessDenied:
            return False

    def __enter__(self):
        if self.is_running():
            raise AlreadyRunningError
        with open(self._file, "w") as f:
            f.write(str(os.getpid()))
        return self

    def __exit__(self, *args):
        if os.path.exists(self._file):
            try:
                os.remove(self._file)
            except OSError:
                pass
