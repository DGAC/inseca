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


import os
import hashlib
import random
import Utils as util

max_hole=768*1024 # 768 kb


def _generate_random_chunks(totalsize, maxchunksize=700, minchunksize=200, minsep=100, maxsep=500, start_after=0):
    """Create random chunks and outputs them as a list of [starting position, length], ex:
    [[0, 437], [930, 70]]"""
    random.seed()
    segments=[]
    start=start_after
    index=start
    while index<totalsize:
        if index==start:
            pos=index
        else:
            pos=index+random.randrange(minsep, maxsep)
        if pos>totalsize:
            break
        length=random.randrange(minchunksize, maxchunksize)
        if pos+length>totalsize:
            length=totalsize-pos
        segments+=[[pos, length]]
        index=pos+length
    return segments

#
# Chunks for files
#
def _generate_file_chunks(filename):
    """Generate a chunks zone for the specified file"""
    size=os.path.getsize(filename)
    return _generate_random_chunks(size, maxchunksize=2048, minchunksize=1024, minsep=int(max_hole*2/3), maxsep=max_hole)

def _compute_file_chunks_hash(filename, chunks):
    """Compute the hash for a file using somc ehunks"""
    sha256=hashlib.sha256()
    fd=open(filename, "rb")
    for chunk in chunks:
        fd.seek(chunk[0])
        data=fd.read(chunk[1])
        sha256.update(data)
    return sha256.hexdigest()

def _compute_files_chunks_raw(path, excluded=None, base=None):
    """Generate a dictionary indexed by each file name (relative to @path) found in @path
    in a recursive way.
    Ex: 
    [
    {
        "n": "AppendedData.py",
        "c": [ [0, 1608], [2300, 234]] ],
        "h": "dc8f3309cb4a4398b62b7dbbd107e5c57c2a932ccc820a25e51f0f659113f198",
        "s": 3340
    },
    ...
    ]
    """
    data=[]
    while path.endswith("/"):
        path=path[:-1]
    if base is None:
        base=path
    while base.endswith("/"):
        base=base[:-1]
    if excluded is None:
        excluded=[]

    files=os.listdir(path)
    files.sort()
    for fname in files:
        cfname='%s/%s'%(path, fname)
        rname=cfname[len(base)+1:]
        if rname in excluded:
            print("'%s' is excluded"%rname)
            continue

        if os.path.isdir(cfname):
            res=_compute_files_chunks_raw(cfname, excluded, base)
            data+=res
        elif os.path.islink(cfname):
            # hash the target of the link
            sha256=hashlib.sha256()
            sha256.update(os.readlink(cfname).encode())
            hash=sha256.hexdigest()
            entry={
                "n": rname,
                "c": None,
                "h": hash,
                "s": 0
            }
            data+=[entry]
        elif os.path.isfile(cfname):
            chunks=_generate_file_chunks(cfname)
            hash=_compute_file_chunks_hash(cfname, chunks)
            entry={
                "n": rname,
                "c": chunks,
                "h": hash,
                "s": os.path.getsize(cfname)
                }
            data+=[entry]
    return data

def compute_files_chunks(path, excluded=None):
    """Generate data which can later be verified using _check_files_chunks_hash().
    The chunks AND the associated hashes are generated at the same time.
    ex:
    [
    [
        {
            "n": "AppendedData.py",
            "c": [ [0, 1608], [2300, 234]] ],
            "s": 3340,
            "l": "f090c"
        },
        {
            "n": "Boot.py",
            "c": [ [0, 2029] ],
            "s": 2300,
            "l": "85837"
        }
        ...
    ],
    "2e25ffb9fec946b26f3eebfa1c0be876bdb9a150b2158fc42a3448f2cf1e148e"
    ]

    where "l" is the start of the cumulated hash up to that point
    """
    data=_compute_files_chunks_raw(path, excluded, None)
    # format output
    result=[]
    log=[]
    sha256=hashlib.sha256()
    for entry in data:
        sha256.update(entry["n"].encode())
        sha256.update(b"/")
        sha256.update(entry["h"].encode())
        sha256.update(b"/")
        l=sha256.hexdigest()[:5]
        nentry={
            "n": entry["n"],
            "c": entry["c"],
            "s": entry["s"],
            "l": l
        }
        result+=[nentry]
        log+=[{entry["n"]: l}]
    return (result, sha256.hexdigest(), log) # (hash data, final hash, files hashing log)

def verify_files_chunks(path, chunks, excluded=None):
    """Verifies if the From @data (produced by compute_files_chunks())
    and returns the computed hash with the log"""
    if excluded is None:
        excluded=[]
    # check present files
    handled_files=[]
    log=[]
    sha256=hashlib.sha256()
    for entry in chunks:
        fname="%s/%s"%(path, entry["n"])
        handled_files+=[entry["n"]]
        if entry["n"] in excluded:
            print("Ignore Exclude '%s'"%entry["n"])
            continue
        if os.path.islink(fname):
            # symlink
            if entry["c"] is not None:
                raise Exception("'%' is now a symlink"%fname)
            ssha256=hashlib.sha256()
            ssha256.update(os.readlink(fname).encode())
            filehash=ssha256.hexdigest()
        else:
            if os.path.exists(fname):
                # regular file
                if os.path.getsize(fname)!=entry["s"]:
                    raise Exception("Size of file '%s' has been changed from %s to %s"%(entry["n"],
                                    entry["s"], os.path.getsize(fname)))
                if entry["c"] is None:
                    raise Exception("'%' should be a symlink"%fname)
                filehash=_compute_file_chunks_hash(fname, entry["c"])
            else:
                raise Exception("File '%s' not found"%entry["n"])
        sha256.update(entry["n"].encode())
        sha256.update(b"/")
        sha256.update(filehash.encode())
        sha256.update(b"/")
        cumul=sha256.hexdigest()[:5]
        log+=[{entry["n"]: cumul}]
        #print("VERIF for '%s' => %s"%(entry["n"], sha256.hexdigest()))
        if cumul!=entry["l"]:
            raise Exception("File '%s' has been modified"%entry["n"])
    final=sha256.hexdigest()

    # check that no new file has been added
    def _get_rec_listdir(path, base=None):
        if base==None:
            base=path
        res=[]
        files=os.listdir(path)
        files.sort()
        for fname in files:
            cfname="%s/%s"%(path, fname)
            if os.path.isdir(cfname):
                res+=_get_rec_listdir(cfname, base=base)
            else:
                res+=[cfname[len(base)+1:]]
        return res

    allfiles=_get_rec_listdir(path)
    for fname in allfiles:
        if fname not in handled_files:
            if excluded is not None and fname in excluded:
                continue
            raise Exception("File '%s' has been added"%fname)

    # returns the actual final hash
    return (final, log)


#
# Chunks for a partition
#
def generate_partition_chunks(devfile):
    """Genetate the chunks (not the actual hash for those chunks) for a partition"""
    (size, sector)=util.get_disk_sizes(devfile)
    return _generate_random_chunks(size, maxchunksize=2048, minchunksize=1024, minsep=int(max_hole*2/3), maxsep=max_hole)

def compute_partition_chunks_hash(devfile, chunks):
    """Compute a partition hash with regards to the specified chunks"""
    return _compute_file_chunks_hash(devfile, chunks)

