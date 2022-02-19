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

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

import Jobs as jobs
import Utils as util

#
# support component UI
#
class Component:
    """Initalization of an admin device (where the internal partition has not yet been created)"""
    def __init__(self, ui, builder, live_context):
        self._ui=ui
        self._context=live_context

        self._page_widget=builder.get_object("authn-form")
        self._password=builder.get_object("authn-password")
        self._password.connect("activate", self._unlock_device)

        bbox=builder.get_object("actions-bbox")
        self._btn_validate=Gtk.Button(label="Unlock")
        bbox.add(self._btn_validate)
        self._btn_validate.connect("clicked", self._unlock_device)

    def page_shown_cb(self, page_widget):
        if page_widget==self._page_widget:
            self._btn_validate.show()
        else:
            self._btn_validate.hide()

    def _unlock_device(self, dummy):
        """Actually initialize the device: create the internal partition"""
        pw=self._password.get_text() # user's password
        self._ui.show_message("Unlocking device")
        try:
            # create the internal partition and copy the configuration in it
            job=jobs.AdminDeviceUnlockJob(self._context, pw, self._ui.feedback_component)
            job.start()
            job.wait_with_ui()
            if job.exception is not None:
                util.print_event("Failed: %s"%str(job.exception))
                raise job.exception
            self._password.set_text("") # clear the password field
            self._ui.show_page("menu")
        except Exception as e:
            self._ui.show_error(str(e))
            self._ui.show_page("authn")
    