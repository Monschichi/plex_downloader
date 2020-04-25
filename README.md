# Plex Downloader
[![Updates](https://pyup.io/repos/github/Monschichi/plex_downloader/shield.svg)](https://pyup.io/repos/github/Monschichi/plex_downloader/)
[![Maintainability](https://api.codeclimate.com/v1/badges/edefb6e5098b8c1038fd/maintainability)](https://codeclimate.com/github/Monschichi/plex_downloader/maintainability)

This tool will download specified unseen movies/series from a given [Plex](https://plex.tv/) server. Marks downloaded files as seen to avoid redownload.
Now with resume, progressbar and Bandwidth limit.

Username/Password is stored in ```.netrc``` e.g.:
```
machine plex
  login USERNAME
  password TOPSECRET
```

Install needed python modules:
```
pip3 install --user -r requirements.txt
```

see `downloader.py --help` for usage.

## Credits
Dependencies scanned by [PyUp.io](https://pyup.io/)