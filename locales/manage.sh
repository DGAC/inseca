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

declare -a domains=("inseca")

function update_templates
{
    echo "Updating templates, domain 'inseca'"
    rm -f inseca.pot
	xgettext -d "inseca" -p . -L Python -o "inseca.pot" ../tools/inseca
    xgettext -d "inseca" -p . -L Python -o "inseca.pot" ../lib/*.py

    resdir="../components/inseca-live-wks/opt/inseca"
    xgettext -d "inseca" -p . -L Python -j -o "inseca.pot" "$resdir/startup"
    xgettext --sort-output --keyword=translatable -d "inseca" -j -o "inseca.pot" "$resdir/main.ui"

    resdir="../components/inseca-config/opt/inseca-config"
    xgettext --sort-output --keyword=translatable -d "inseca" -j -o "inseca.pot" "$resdir/main.ui"

    resdir="../components/VPN-OpenVPN/live-config"
    xgettext -d "inseca" -p . -L Python -j -o "inseca.pot" "$resdir/infos.py"

    echo "Updating templates, domain 'inseca-lib'"

    # create the PO file which don't yet exist (for example when a new domain is created)
    for domain in "${domains[@]}"
    do
        for lang in *
        do
            [ -d "$lang" ] && [ ! -f "$lang/LC_MESSAGES/$domain.po" ] && {
                msginit --locale="$lang" --input="$domain.pot" --no-translator -o "$lang/LC_MESSAGES/$domain.po"
            }
        done
    done
}

function update_transl
{
    lang="$1"
    domain="$2"

    echo "Updating '$lang' translations for domain '$domain'"

    pofile="$lang/LC_MESSAGES/$domain.po"
    [ -f "$pofile" ] || {
        echo "Translations file '$pofile' does not exist"
        exit 1
    }
    templ="$domain.pot"
    [ -f "$templ" ] || {
        echo "Template file '$templ' does not exist"
        exit 1
    }

    msgmerge "$pofile" "$templ" -o "$lang/LC_MESSAGES/$domain.po" || {
        echo "Failed to update translation '$lang'"
        exit 1
    }
}

function compile_transl
{
    lang="$1"
    domain="$2"

    echo "Compiling '$lang' translations for domain '$domain'"

    pofile="$lang/LC_MESSAGES/$domain.po"
    [ -f "$pofile" ] || {
        echo "Translations file '$pofile' does not exist"
        exit 1
    }

    msgfmt "$pofile" -o "$lang/LC_MESSAGES/$domain.mo" || {
        echo "Failed to compile translation '$lang'"
        exit 1
    }
}

function init_transl
{
    lang="$1"
    echo "Initializing '$lang' translations"

    [ -e "$lang" ] && {
        echo "Translation '$lang' already exists"
        exit 1
    }

    mkdir -p "$lang/LC_MESSAGES" || {
        echo "Failed to initialize translation '$lang'"
        exit 1
    }

    for domain in "${domains[@]}"
    do
        msginit --locale="$lang" --input="$domain.pot" --no-translator -o "$lang/LC_MESSAGES/$domain.po"
    done
}

case "$1" in
    update)
        update_templates
        for lang in *
        do
            [ -d "$lang" ] && [ -d "$lang/LC_MESSAGES" ] && {
                for domain in "${domains[@]}"
                do
                    update_transl "$lang" "$domain"
                done
            }
        done
        ;;
    compile)
        for lang in *
        do
            [ -d "$lang" ] && [ -d "$lang/LC_MESSAGES" ] && {
                for domain in "${domains[@]}"
                do
                    compile_transl "$lang" "$domain"
                done
            }
        done
        ;;
    init)
        [ "$2" == "" ] && {
            echo "$0 init <lang>"
            exit 1
        }
        init_transl "$2"
        ;;
    *)
        echo "$0 update | compile | init <lang>"
        exit 1
        ;;
esac
