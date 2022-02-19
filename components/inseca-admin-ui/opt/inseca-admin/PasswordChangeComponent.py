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

import CryptoGen as cgen
import Jobs as jobs
import Utils as util

#
# support component UI
#
class Component:
    """Allow one to change its password"""
    def __init__(self, ui, builder, live_context):
        self._ui=ui
        self._context=live_context

        self._page_widget=builder.get_object("pass-change-form")
        self._current_password=builder.get_object("current-password")
        self._password1=builder.get_object("change-password1")
        self._password2=builder.get_object("change-password2")

        self._password1.connect("changed", self._password_entry_changed)
        self._password2.connect("changed", self._password_entry_changed)
        self._password1.connect("activate", self._password_change)
        self._password2.connect("activate", self._password_change)

        bbox=builder.get_object("actions-bbox")
        self._btn_validate=Gtk.Button(label="Change password")
        bbox.add(self._btn_validate)
        self._btn_validate.connect("clicked", self._password_change)
        self._btn_validate.set_sensitive(False)

    def page_shown_cb(self, page_widget):
        if page_widget==self._page_widget:
            self._btn_validate.show()
        else:
            self._btn_validate.hide()

    def _password_entry_changed(self, dummy):
        """Called when an entry to define the password has been changed"""
        pw1=self._password1.get_text()
        pw2=self._password2.get_text()
        self._btn_validate.set_sensitive(pw1==pw2 and pw1!="")

    def _password_change(self, dummy):
        """Actually change the password"""
        npw=self._password1.get_text() # user's password
        cgen.validate_password(npw)
        self._ui.show_message("Changing password...")
        try:
            cpw=self._current_password.get_text()
            job=jobs.PasswordChangeJob(self._context, cpw, npw, self._ui.feedback_component)
            job.start()
            job.wait_with_ui()
            if job.exception is not None:
                util.print_event("Failed: %s"%str(job.exception))
                raise job.exception
            self._ui.show_page("menu")

            # reset password text fields 
            self._current_password.set_text("")
            self._password1.set_text("")
            self._password2.set_text("")
        except Exception as e:
            self._ui.show_error(str(e))
            self._ui.show_page("pass-change-form")
    