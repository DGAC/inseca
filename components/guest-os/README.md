Guest OS in a "short lived" virtual machine.

Required package: fairshell-virt-system from https://github.com/VivienMla/fairshell-virt-system

# Build configuration attributes

- **config**: 
Configuration file for the VM (refer to the documentation), for example:
{
    "win10": {
        "vm-imagefile": "/internal/guest-os/guest-os.img",
        "descr": "Windows environment",
        "shared-dir": "Documents",
        "display": "fullscreen",
        "writable": false,
        "hardware": {
            "mem": 3072,
            "cpu": 2
        },
        "allowed-users": ["insecauser"],
        "resolved-names": [
            "globalsign.com",
            "digicert.com",
            "thawte.com",
            "amazontrust.com"
        ],
        "allowed-networks": []
    },
}

NB:
- from the example above, only the "descr", "display", "hardware", "resolved-names" and "allowed-networks"
  keys should be modified (leave the rest unchanged)

# USERDATA attributes

- **os-image**: VM image file, refer to the doc. on how to create it