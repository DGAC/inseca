Teams & Zoom.

# Build configuration attributes

none

# USERDATA attributes

none

# Packages download

- [Teams](https://www.microsoft.com/fr-fr/microsoft-teams/download-app)
- [Zoom](https://zoom.us/download)

And rename the packages using `dpkg-name <pkgname>`

# Teams

- proper integration: https://linuxiac.com/how-to-install-microsoft-teams-on-linux-from-the-official-ms-repository/
- Web page download: https://www.microsoft.com/fr-fr/microsoft-teams/download-app
- Proxy config:
  ~~~
  teams --proxy-server=http://proxy-host:proxy-port
  --proxy-pac-url=https://pac.server.com/file.pac
  ~~~
- sinon, faire un strings /usr/share/teams/teams
- cf. https://doc.ubuntu-fr.org/teams

# References

- https://gitlab.com/parrot_parrot/ms-teams-replace-background
- https://github.com/IsmaelMartinez/teams-for-linux
- screen sharing with wayland:
  - https://github.com/electron/electron/issues/23063
  - https://microsoftteams.uservoice.com/forums/555103-public/suggestions/41524504-screen-sharing-on-wayland
- https://github.com/IsmaelMartinez/teams-for-linux