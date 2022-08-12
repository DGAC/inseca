Main component to manage a running INSECA system with a GUI.

# Build configuration attributes

- **userdata-skey-pub-file**: public key used to verify the signature of USERDATA resources,
  relative to the build's config file
- **allowed-virtualized**: list of virtual environments in which the devices is allowed to be used as a CSV or "", refer to systemd-detect-virt's man page
- **disabled-net-services**: list of INSECA's network services to disable, as a CSV of:
  - `all`: disable all services
  - `updates`: disable the live Linux updates service
- NOT YET **network-connections-allowed**: boolean indicating if the network stack (managed by NetworkManager) is enabled
  (which allows the user to connect to wired or wireless networks) or disabled
- NOT YET **network-allow-list**: if defined, the network access is denied by default and restricted only to the
  provided list of system names and/or IP address ranges.

# USERDATA attributes

none