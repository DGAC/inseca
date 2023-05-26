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

import subprocess
import time
import os
import syslog
import requests
import Utils as util

# define a proxy.pac file here
proxy_pac_file=None
internet_ref_site="http://www.google.com"

import threading
from gi.repository import GLib
import dbus
import dbus.mainloop.glib
class NetworkMonitor(threading.Thread):
    """Monitors network configuration using NetworkManager's API in a sub thread.
    Use the @changed property to check if the network settings have changed since last check.
    Call stop_monitoring() when finished using the object"""
    def __init__(self):
        threading.Thread.__init__(self)
        self._changed=False
        self._loop=None
        self._timer_id=None
        self._start_monitoring()

    @property
    def changed(self):
        chg=self._changed
        self._changed=False
        return chg

    def _start_monitoring(self):
        """Start the sub thread and wait for it to be started and 'operational'"""
        self.start() # start the sub thread
        while True:
            if self._loop and self._loop.is_running():
                break
            time.sleep(0.2)

    def stop(self):
        """Stop the monitoring"""
        self._changed=False
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id=None
        if self._loop:
            self._loop.quit()
            while self._loop.is_running():
                time.sleep(0.2)
            self._loop=None
        try:
            self.join()
        except Exception:
            pass

    def _changed_cb(self):
        self._timer_id=None
        self._changed=True
        return False # don't keep timer

    def _net_state_changed_cb(self, dummy):
        """Function called when the NM's properties change, it can be called several times in a short amount of
        time => use a timer to run the self._changed_cb() function"""
        if self._timer_id is None:
            self._timer_id=GLib.timeout_add(500, self._changed_cb) # to "aggregate" several property notifications in one call

    def run(self):
        # monitor NetworkManager through its DBus interfaces
        NM_DBUS_NAME = "org.freedesktop.NetworkManager"
        NM_DBUS_PATH = "/org/freedesktop/NetworkManager"
        NM_DBUS_INTERFACE = "org.freedesktop.NetworkManager"

        # set up NetworkManager monitoring
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        sessionBus = dbus.SystemBus()
        nm_proxy=sessionBus.get_object(NM_DBUS_NAME, NM_DBUS_PATH)
        nm_proxy.connect_to_signal("PropertiesChanged", self._net_state_changed_cb, dbus_interface=NM_DBUS_INTERFACE)

        self._loop=GLib.MainLoop()
        self._loop.run()


class SyncConfig:
    """Synchronization 'endpoint' (or method), to map to the 'deploy' section of the global inseca.json configuration file"""
    def __init__(self, name, root, conf_file=None):
        self._name=name
        self._root=root
        self._conf_file=conf_file # not None => RClone 'endpoint'

    @property
    def name(self):
        return self._name

    @property
    def conf_file(self):
        return self._conf_file

    @property
    def is_local(self):
        """Tells if this Sync. config. operates on local mass storage devices"""
        if self._conf_file:
            return False
        return True

    @property
    def root_conf(self):
        """Get the prefix to use with that Sync. config: either a path or an RClone syntax.
        This is the actual root as defined in the configuration, see the "roo" property
        for a contextualized information"""
        return self._root

    @property
    def root(self):
        """Get the prefix to use with that Sync. config: either a path or an RClone syntax.
        If it's a non absolute path, then the mounted devices will be searched and the one containing this path
        from its root will be used."""
        if self._conf_file: # RClone 'endpoint'
            return self._root

        if os.path.isabs(self._root):
            if os.path.isdir(self._root):
                return self._root
            raise Exception("Path '%s' does not exist or is not a directory"%self._root)

        # find a plugged mass storage which contains the self._path relative path (from its root)
        fpath=_find_plugged_device_with_path(self._root)
        if fpath is None:
            raise Exception("No plugged device")
        return fpath

    @property
    def is_available(self):
        """Tells if this Sync. config is currently available: if there is Internet acces or if there
        is a mass storage device plugged containing the self._root directory"""
        if self._conf_file:
            return internet_accessible()
        else:
            try:
                path=self.root
                return True
            except Exception:
                return False

def _find_plugged_device_with_path(rel_path):
    (status, out, err)=util.exec_sync(["lsblk", "-o", "MOUNTPOINT"])
    if status!=0:
        raise Exception("Could not search for external mass storage: %s"%err)
    for line in out.splitlines():
        fpath="%s/%s"%(line, rel_path)
        if os.path.exists(fpath):
            return fpath
    return None

class SyncLocation:
    """Association between a SyncConfig and a relative path to form an actual repository/directory definition which can be
    used as the source or destination of a synchronization using RCLone"""
    def __init__(self, rel_path, sync_obj=None):
        if sync_obj is not None:
            if not isinstance(sync_obj, SyncConfig):
                raise Exception("Code bug: @sync_obj should be a SyncConf object")
        self._path=rel_path
        self._sync_obj=sync_obj

    @property
    def path(self):
        if self._sync_obj:
            return "%s/%s"%(self._sync_obj.root, self._path)
        else:
            return self._path

    @property
    def conf_file(self):
        if self._sync_obj is None:
            return None
        return self._sync_obj.conf_file

    @property
    def is_local(self):
        if self._sync_obj is None: 
            return True
        return self._sync_obj.is_local

    @property
    def is_available(self):
        if self._sync_obj:
            return self._sync_obj.is_available
        else:
            return True

def _parse_rclone_stats(text):
    units={
        "Bytes": 1,
        "kBytes": 1000,
        "MBytes": 1000*1000,
        "GBytes": 1000*1000*1000
    }
    stats=None
    for line in text.splitlines():
        if line.startswith("Transferred:"):
            try:
                # like: Transferred:   1.230 GBytes (5.068 MBytes/s)
                # like \x1b....Transferred:    \t 0 / 0 Bytes
                line=line.split("Transferred:")[1].strip()
                parts=line.split()
                if len(parts)>=9:
                    if stats is None:
                        stats={}
                    try:
                        stats["percent"]=int(float(parts[4][:-2]))
                    except:
                        stats["percent"]=0

                    rate=float(parts[5])
                    (unit, dummy)=parts[6].split("/", 1)
                    if unit not in units:
                        raise Exception()
                    value=(float(rate))*units[unit]
                    stats["rate_bps"]=int(value)
                    stats["remain"]=parts[8]
            except:
                pass
        elif line.startswith("Checks:"):
            try:
                # like: Checks:               292 / 350, 83%
                line=line.split("Checks:")[1].strip()
                parts=line.split()
                if stats is None:
                    stats={}
                stats["checks"]=int(parts[3][:-1])
            except:
                pass

    return stats

def _rclone_stats_to_string(stats):
    """Update the UI with a job running rclone"""
    if stats:
        if "rate_bps" in stats:
            rate=stats["rate_bps"]
            if rate>=10**6:
                rs="%.2f Mb/s"%(rate/10**6)
            elif rate>=10**3:
                rs="%.2f Kb/s"%(rate/10**3)
            else:
                rs="%.2f b/s"%rate
            if stats["remain"]!="-":
                if stats["percent"]==100 or stats["percent"]<2:
                    # sometimes the RClone stats are wrong => only display reliable tx rate
                    details=rs
                else:
                    details="%s%% transferred (%s)"%(stats["percent"], rs)
                return details
            else:
                return None
        elif "checks" in stats:
            return "%s%% done checking"%stats["checks"]
    else:
        return None

def _extract_rclone_err_message_for_user(err):
    """As rclone error message can be large, extract some usefull information for the user"""
    lines=err.splitlines()
    lines=lines[-2:]
    return "\n".join(lines)

def _adjust_time(exec_env=None):
    """Adjust the time to remove any skew. It requires an Internet access.
    The @exec_env allows one to specify a proxy fore example.
    """
    try:
        res=requests.get(internet_ref_site)
        if res.ok:
            # get current date (UTC)
            (status, outh, errh)=util.exec_sync(["date", "-d", "now", "+%s"]) # '%s' is always in UTC
            if status==0:
                host_ts=int(outh)
            else:
                syslog.syslog(syslog.LOG_ERR, "Could not get current host time: %s"%errh)
                return

            remote_ts_str=res.headers["Date"]
            syslog.syslog(syslog.LOG_INFO, "Got time from remote '%s': %s"%(internet_ref_site, remote_ts_str))
            (status, out, err)=util.exec_sync(["date", "-d", remote_ts_str, "+%s"]) # NB: we use the date command line tool as Python seems unable to
                                                                                    # parse timezones, see https://stackoverflow.com/questions/3305413/how-to-preserve-timezone-when-parsing-date-time-strings-with-strptime
            if status==0:
                remote_ts=int(out)
            else:
                syslog.syslog(syslog.LOG_ERR, "Could not convert remote time: %s"%err)
                return

            if abs(remote_ts-host_ts)>10:
                # adjust current time
                syslog.syslog(syslog.LOG_INFO, "Adjusting host time to remote")
                (status, out, err)=util.exec_sync(["date", "-s", remote_ts_str, "--utc"])
                if status==0:
                    pass
                else:
                    syslog.syslog(syslog.LOG_ERR, "Could not adjust date to '%s': %s"%(remote_ts_str, err))
            else:
                syslog.syslog(syslog.LOG_INFO, "No local time adjustment necessary (%ss shift)"%(remote_ts-host_ts))
        else:
            raise Exception(res.text)
    except Exception as e:
        syslog.syslog(syslog.LOG_ERR, "Could not get time from Internet server '%s': %s"%(internet_ref_site, str(e)))

def _read_stderr(process):
    """Read and return stderr as a str"""
    try:
        err=os.read(process.stderr.fileno(), 1024)
        return err.decode()
    except:
        return ""

class RcloneSync:
    def __init__(self, src, dest, exec_env=None):
        if not isinstance(src, SyncLocation):
            raise Exception("Code bug: @src should be a SyncLocation object")
        if not isinstance(dest, SyncLocation):
            raise Exception("Code bug: @dest should be a SyncLocation object")
        if not src.is_local and not dest.is_local:
            raise Exception("Can't synchronize between two remote locations")
        self._src=src
        self._dest=dest
        self._exec_env=exec_env

    def sync(self, add_event_func=None):
        if self._src.is_local:
            conf_file=self._dest.conf_file
        else:
            conf_file=self._src.conf_file
        if conf_file:
            args=["rclone", "--config", conf_file]
        else:
            args=["rclone"]
        args+=["--progress", "--stats=1s","sync", self._src.path, self._dest.path]

        # network monitoring
        nm=NetworkMonitor()

        # rclone process
        from fcntl import fcntl, F_GETFL, F_SETFL
        from os import O_NONBLOCK
        restart=True
        err=None
        status=None
        index=0
        while restart: # loop to (re)start the rclone process
            if not self._dest.is_available:
                nm.stop()
                raise Exception("Resource's destination is not available")
            if not self._src.is_available:
                nm.stop()
                raise Exception("Resource's origin is not available")

            # prepare proxy, if any
            proxies=find_suitable_proxy(url=internet_ref_site)
            if proxies:
                env={}
                if self._exec_env:
                    env=self._exec_env.copy()
                env["https_proxy"]=proxies["https"]
                env["http_proxy"]=proxies["http"]
            else:
                env=None
                if self._exec_env is not None:
                    env=self._exec_env.copy()
                    for varname in ("https_proxy", "http_proxy"):
                        if varname in env:
                            del env[varname]

            # ensure local time is correct to avoid RClone failure like
            # Failed to sync: RequestTimeTooSkewed: The difference between the request time and the current time is too large.
            _adjust_time(env)

            # run an rclone process
            index+=1
            syslog.syslog(syslog.LOG_INFO, "Starting RClone (%s): %s"%(index, " ".join(args)))
            syslog.syslog(syslog.LOG_INFO, "Started RClone with env: %s"%env)
            process=subprocess.Popen(args, env=env, bufsize=0, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            flags=fcntl(process.stdout, F_GETFL) # get current p.stdout flags
            fcntl(process.stdout, F_SETFL, flags | O_NONBLOCK)
            flags=fcntl(process.stderr, F_GETFL) # get current p.stdout flags
            fcntl(process.stderr, F_SETFL, flags | O_NONBLOCK)
            time.sleep(1) # wait for RCLone to actually start
            status=None

            # handle this process
            while True:
                # if network has changed, we restart the rclone process
                if nm.changed:
                    syslog.syslog(syslog.LOG_WARNING, "Network config changed => restart RClone")
                    restart=True
                    break

                # check if process has finished
                status=process.poll()
                if status!=None:
                    syslog.syslog(syslog.LOG_INFO, "RClone has finished, status: %s"%status)
                    restart=False # rclone has finished
                    break

                # read and process the rclone output
                try:
                    time.sleep(0.5)
                    out=os.read(process.stdout.fileno(), 1024)
                    if out:
                        try:
                            stats=_parse_rclone_stats(out.decode())
                            if stats:
                                msg=_rclone_stats_to_string(stats)
                                if msg is not None:
                                    if add_event_func:
                                        add_event_func(msg)
                                    else:
                                        util.print_event(msg)
                        except:
                            # could not parse rclone stats
                            pass
                    err=_read_stderr(process)
                    if err:
                        syslog.syslog(syslog.LOG_WARNING, "RCLone output error: %s"%err)
                        util.print_event("RClone output error: %s"%err, log=False)
                except OSError as e:
                    # we may get a lot of Resource temporarily unavailable errors
                    if e.errno!=11:
                        syslog.syslog(syslog.LOG_WARNING, "RCLone OSError: %s"%str(e))
                        util.print_event("RClone OSError: %s"%str(e), log=False)
                        restart=False
                        break
                except Exception as e:
                    err=str(e)
                    if "retry later" in err:
                        # we sometimes get the "Incomplete synchronisation, retry later" error => wait a bit and retry
                        time.sleep(5)
                        restart=True
                        break
                    else:
                        syslog.syslog(syslog.LOG_WARNING, "RCLone error: %s"%err)
                        util.print_event("RClone Error: %s"%err, log=False)
                        restart=False
                        break

        # read stderr
        err=_read_stderr(process)

        # properly get rid of the rclone process
        try:
            process.kill()
        except:
            pass
        process.wait()

        # stop network monitoring
        nm.stop()

        # final statement
        if status!=None and status!=0:
            if err:
                raise Exception("Data synchronisation error: %s"%_extract_rclone_err_message_for_user(err))
            else:
                raise Exception("Data synchronisation error")

#
# Internet access
#
def get_ip():
    import socket
    s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 53)) # we don't care if not reacheable
        #print("IP: %s"%s.getsockname()[0])
        return s.getsockname()[0]
    except:
        return "127.0.0.1"
    finally:
        s.close()

def find_suitable_proxy(url="http://www.debian.fr"):
    if os.environ.get("INSECA_NO_HTTP_PROXY")=="1":
        return None
    if proxy_pac_file is None:
        syslog.syslog(syslog.LOG_INFO, "find_suitable_proxy() => None: no PAC file")
        return None
    try:
        ip=get_ip()
        if ip=="127.0.0.1":
            return None

        try:
            proxies="DIRECT"
            # may fail if the proxy PAC file can't be read
            import pacparser
            pacparser.init()
            pacparser.parse_pac_file(proxy_pac_file)
            pacparser.setmyip(ip)
            proxies=pacparser.find_proxy(url)

            if proxies.startswith("DIRECT"):
                syslog.syslog(syslog.LOG_INFO, "find_suitable_proxy() => None: DIRECT route for IP %s"%ip)
                return None
            parts=proxies.split(";")
            util.print_event("Using HTTP proxy: %s"%proxies)
            proxyline=parts[0] # take the 1st proposed proxy
            (dummy, proxy)=proxyline.split() # proxyline ex: PROXY proxy1.manugarg.com:3128
            syslog.syslog(syslog.LOG_INFO, "find_suitable_proxy() => %s for IP %s"%(proxy, ip))
            return {
                "http": "http://"+proxy,
                "https": "http://"+proxy,
            }
        except Exception:
            res={}
            if "http_proxy" in os.environ:
                res["http"]=os.environ["http_proxy"]
                res["https"]=os.environ["http_proxy"]
            if len(res)>0:
                syslog.syslog(syslog.LOG_INFO, "find_suitable_proxy() => %s from httpX_proxy env. variable"%res)
                return res
            syslog.syslog(syslog.LOG_INFO, "find_suitable_proxy() => None from no httpX_proxy env. variable")
            return None
    except Exception as e:
        syslog.syslog(syslog.LOG_ERR, "Could not find a proxy to use: %s"%str(e))
        raise e

def internet_accessible(exception_if_false=False):
    try :
        import requests
        url=internet_ref_site
        proxies=find_suitable_proxy(url)
        if proxies is None: # force no proxy (make sure any http_proxy env. variable is ignored)
            proxies = {
                "http": None,
                "https": None,
            }
        requests.get(url, timeout=3, proxies=proxies)
        return True
    except Exception as e:
        if exception_if_false:
            raise e
        return False
