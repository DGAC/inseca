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
    """Initalization of an admin device (where the internal partition has not yet been created)"""
    def __init__(self, ui, builder, live_context):
        self._ui=ui
        self._context=live_context

        self._page_widget=builder.get_object("init-form")
        self._access_code=builder.get_object("init-access-code")
        self._password1=builder.get_object("init-password1")
        self._password2=builder.get_object("init-password2")

        self._password1.connect("changed", self._password_entry_changed)
        self._password2.connect("changed", self._password_entry_changed)
        self._password1.connect("activate", self._init_device)
        self._password2.connect("activate", self._init_device)

        bbox=builder.get_object("actions-bbox")
        self._btn_validate=Gtk.Button(label="Validate")
        bbox.add(self._btn_validate)
        self._btn_validate.connect("clicked", self._init_device)
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

    def _init_device(self, dummy):
        """Actually initialize the device: create the internal partition"""
        pw=self._password1.get_text() # user's password
        cgen.validate_password(pw)

        self._ui.show_message("Initializing device...")
        try:
            # decrypt the configuration
            code=self._access_code.get_text()
            conf_file=self._context.decrypt_config(code)

            # random password for the encrypted partition
            ipw=cgen.generate_password()

            # create the internal partition and copy the configuration in it
            job=jobs.AdminDeviceInitJob(self._context, ipw, conf_file.name, self._ui.feedback_component)
            job.start()
            job.wait_with_ui()
            if job.exception is not None:
                util.print_event("Failed: %s"%str(job.exception))
                raise job.exception

            # declare user
            self._context.declare_user("INSECA administrator", pw, ipw)

            self._ui.show_page("authn")
        except Exception as e:
            self._ui.show_error(str(e))
            self._ui.show_page("init")
    