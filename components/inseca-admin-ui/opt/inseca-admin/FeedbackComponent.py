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
#    along with INSECA.  If not, see <https://www.gnu.org/licenses/>

import queue

from gi.repository import GLib

#
# resources update UI
#
class Component:
    """UI to show a feedback to the user"""
    def __init__(self, ui, builder):
        self._ui=ui
        self._builder=builder
        self._queue=queue.Queue()
        self._page_widget=self._builder.get_object("feedback")
        self._message_widget=self._builder.get_object("message")
        self._timer=None

    def page_shown_cb(self, page_widget):
        if page_widget==self._page_widget:
            # this page is now shown
            if self._timer is None:
                self._timer=GLib.timeout_add(100, self._update_message)
        else:
            # this page is now hidden
            if self._timer is not None:
                GLib.source_remove(self._timer)
                self._timer=None

    def add_event(self, msg):
        """Add an event message to be displayed, can be called from any thread"""
        try:
            self._queue.put_nowait(msg)
        except queue.Full:
            pass

    def _update_message(self):
        msg=None
        while True:
            try:
                msg=self._queue.get_nowait()
                print("... %s"%msg)
            except queue.Empty:
                break
        if msg:
            if len(msg)>80:
                msg=msg[:77]+"..."
            self._message_widget.set_text(msg)
        return True # keep the timer
