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

import Configurations

#
# support component UI
#
class Component:
    """Providing support for an already created INSECA installation"""
    def __init__(self, ui, builder):
        self._page_widget=builder.get_object("menu")
        self._resources_button=builder.get_object("button-manage-resources")
        self._install_button=builder.get_object("button-install")
        self._format_button=builder.get_object("button-format")
        self._support_button=builder.get_object("button-support")

    def page_shown_cb(self, page_widget):
        self._install_button.hide()
        self._format_button.hide()
        self._support_button.hide()
        if page_widget==self._page_widget:
            try:
                gconf=Configurations.get_gconf()
                if gconf.is_master:
                    self._resources_button.hide()
                else:
                    self._resources_button.show()
                if len(gconf.install_configs)>0:
                    self._install_button.show()
                if len(gconf.format_configs)>0:
                    self._format_button.show()
                if len(gconf.install_configs)>0 or len(gconf.format_configs)>0:
                    self._support_button.show()
            except Exception:
                pass
