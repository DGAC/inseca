#!/bin/bash

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

set -e

mkdir -p "$LIVE_DIR/opt/inseca-admin"

# copy inseca program itself
cp "$LIBS_DIR/../tools/inseca" "$LIVE_DIR/opt/inseca-admin"
# copy resources
tar cf - -C "$LIBS_DIR/../tools" resources | tar xf - -C "$LIVE_DIR/opt/inseca-admin"
