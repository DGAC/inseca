Defines resources consumption limits mechanism using control groups, implemented by
the `inseca-cgroups.service` systemd service.

Actual definitions must be placed in:

- ` etc/cgconfig.d/`: files containing the groups definitions
- ` etc/cgrules.d/`: files containing the actual rules to place programs in groups

Changes with Debian 11:
- cgroup v2 is the default
- cgroup v1 exists but is not mounted
- the libcgroup has been ported to cgroup v2 (version 2.0) but not in the Debian 11 => we get it from testing

# Build configuration attributes

none

# USERDATA attributes

none

# Groups config file example

~~~
group browsers {
  perm {
    task {
      uid = insecauser;
      gid = insecauser;
    }
    admin {
      uid = insecauser;
      gid = insecauser;
    }
  }
  cpu {
    cpu.max = "700000 1000000";
  }
  memory {
    memory.max = "2G";
    memory.high = "1900M";
 }
}
~~~

# Rules config file example

~~~
# user:process                                          subsystems      group
*:/usr/lib/chromium-browser/chromium-browser            cpu,memory      browsers
*:/usr/lib/chromium/chrome-sandbox                      cpu,memory      browsers
*:/usr/lib/firefox-esr/firefox-esr                      cpu,memory      browsers
*:/usr/lib/thunderbird/thunderbird-bin			cpu,memory      browsers
*:/usr/share/teams/teams				cpu,memory      browsers
~~~

# References
- [cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)
- [using cgroups to limit browser memory+cpu usage ](https://gist.github.com/hardfire/7e5d9e7ce218dcf2f510329c16517331)