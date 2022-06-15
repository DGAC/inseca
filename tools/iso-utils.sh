#!/bin/bash

# This file is part of INSECA.
#
#    Copyright (C) 2022 INSECA authors
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

set -e

# copy ISO's contents to a RW directory and returns that directory
iso_extract ()
{
    iso_file="$1"
    mnt_dir=$(mktemp -d)
    dest_dir=$(mktemp -d)
    loopdev=$(sudo losetup -f --show -P "$iso_file")
    sudo mount ${loopdev}p1 "$mnt_dir"
    tar cf - -C "$mnt_dir" . | (cd "$dest_dir" && tar xf -)
    sudo umount ${loopdev}p1
    sudo losetup -d /dev/loop0
    rmdir "$mnt_dir"

    # extract isohdpfx.bin
    sudo dd if="$iso_file" of="$dest_dir/.isohdpfx.bin" bs=1 count=432

    echo "$dest_dir"
}

# re-create an ISO image
iso_create ()
{
    iso_dir="$1" # where the contents of the ISO is
    vol_id="$2" # volume ID
    out_file=$(realpath "$3") # created ISO file

    [ -f "$iso_dir/.isohdpfx.bin" ] || {
        logger -p err "Missing (non extracted) .isohdpfx.bin"
        exit 1
    }

    mod=$(date +%Y%m%d%H%M%S00)
    (cd "$iso_dir" && xorriso -as mkisofs -R -r -J -joliet-long -l -cache-inodes -iso-level 3 -isohybrid-mbr "$iso_dir/.isohdpfx.bin" -partition_offset 16 \
                              -A "INSECA" -p "INSECA builder" -publisher "INSECA project" -V "$vol_id" --modification-date=$mod \
                              -b isolinux/isolinux.bin -c isolinux/boot.cat -no-emul-boot -boot-load-size 4 -boot-info-table -eltorito-alt-boot \
                              -e boot/grub/efi.img -no-emul-boot -isohybrid-gpt-basdat -isohybrid-apm-hfsplus \
                              -o  "$out_file" .)
}

# extract initramfs to a RW directory and returns that directory
initramfs_extract ()
{
    initrd_file="$1"
    dest_dir=$(mktemp -d)

    unmkinitramfs "$initrd_file" "$dest_dir"
    echo "$dest_dir"
}

# cre-create initramfs
# if the file to create is not specified, a tmp one is chosen
initramfs_create ()
{
    initrd_dir="$1" # where the contents of the ISO is
    out_file="$2" # created initramfs file

    [ "$outfile" == "" ] && outfile=$(mktemp)

    [ -d "$initrd_dir/early" ] && [ -d "$initrd_dir/main" ] || {
        logger -p err "Invalid initrd files structure"
        exit 1
    }

    cpio_early=$(mktemp)
    (cd "$initrd_dir/early" && find . | cpio --quiet -R 0:0 -o -H newc > "$cpio_early")
    cpio_main=$(mktemp)
    (cd "$initrd_dir/main" && find . | cpio --quiet -R 0:0 -o -H newc > "$cpio_main")
    xz --check=crc32 "$cpio_main"

    mv "$cpio_early" "$out_file"
    cat "$cpio_main.xz" >> "$out_file"
    rm -f "$cpio_main" "$cpio_main.xz"

    echo "$outfile"
}

usage ()
{
    cat <<EOF
Usage: $0 <action> [arguments]
Actions:
    iso-extract         <iso file>
    iso-create          <iso files dir> <volume ID> <out iso file name>
    initramfs-extract   <initrd file>
    initramfs-create    <initrd files dir> [out initrd file name]
EOF
    exit 1
}

case "$1" in
    iso-extract)
        [ "$#" != 2 ] && usage
        iso_extract "$2"
        ;;
    iso-create)
        [ "$#" != 4 ] && usage
        iso_create "$2" "$3" "$4"
        ;;
    initramfs-extract)
        [ "$#" != 2 ] && usage
        initramfs_extract "$2"
        ;;
    initramfs-create)
        [ "$#" != 2 ] && [ "$#" != 3 ] && usage
        initramfs_create "$2" "$3"
        ;;
    *)
        usage
        ;;
esac
