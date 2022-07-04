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
#

# execute long running functions in sub threads

import threading
import time
import Sync

class JobCancelled(Exception):
    def __init__(self):
        Exception.__init__(self, "Cancelled")

class Job(threading.Thread):
    """Execute a 'job' in a sub thread, while allowing to keep the UI responsive"""
    def __init__(self):
        threading.Thread.__init__(self)
        self.exception=None
        self.result=None
        self._cancelled=False

    @property
    def cancelled(self):
        return self._cancelled

    def cancel(self):
        print("Cancel requested")
        self._cancelled=True

    def wait_with_ui(self):
        """To be called from GTK's main loop thread"""
        c=0
        from gi.repository import Gtk
        while Gtk.events_pending:
            Gtk.main_iteration_do(False)
            time.sleep(0.01)
            c+=1
            if c>50:
                c=0
                if not self.is_alive():
                    self.join()
                    if self._cancelled:
                        self.exception=JobCancelled()
                    break

    def wait_finished(self, main_loop):
        """To be called when there is only a main loop"""
        while True:
            context=main_loop.get_context()
            while context.pending():
                context.iteration(False)
            time.sleep(0.1)
            if not self.is_alive():
                self.join()
                if self._cancelled:
                    self.exception=JobCancelled()
                break

    def finished(self):
        """Tells if the job has finished"""
        if not self.is_alive():
            self.join()
            if self._cancelled:
                self.exception=JobCancelled()
            return True
        return False
