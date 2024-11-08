#!/bin/bash

# This file is part of INSECA.
#
#    Copyright (C) 2020-2024 INSECA authors
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
mkdir -p "$LIVE_DIR/opt/inseca"

# make sure the symlinks are replaced by actual copies
pushd "$COMPONENT_DIR/opt/inseca" > /dev/null 2>&1
for file in *
do
    [ -h "$file" ] && {
        rm -f "$LIVE_DIR/opt/inseca/$file"
        cp -aL "$file" "$LIVE_DIR/opt/inseca"
    }
done
popd > /dev/null 2>&1

# copy locales' files
mkdir -p "$LIVE_DIR/opt/inseca/locales"
pushd "$SOURCES_DIR/locales"
tar cf - $(find . -name "*.mo") | tar xf - -C "$LIVE_DIR/opt/inseca/locales"
popd

# copy library components
for file in "$LIBS_DIR/"*
do
    [ -f "$file" ] && { # we don't want directories
        cp -aL "$file" "$LIVE_DIR/opt/inseca"
    }
done