#!/usr/bin/env python3

import argparse
import logging
import netrc
import os
import sys

import pycurl
from plexapi.exceptions import NotFound
from plexapi.library import ShowSection
from plexapi.media import MediaPart
from plexapi.myplex import MyPlexAccount
from plexapi.playlist import Playlist
from plexapi.video import Video
from tqdm import tqdm


class PlexDownloader:
    def __init__(self, target: str, bw_limit: int, show_progress: bool, assets: bool, force: bool, refresh_assets: bool,
                 no_transcoding: bool, timeout: int):
        self.logger = logging.getLogger('download')
        self.target = target
        self.bw_limit = bw_limit
        self.show_progress = show_progress
        self.assets = assets
        self.force = force
        self.refresh_assets = refresh_assets
        self.no_transcoding = no_transcoding
        self.timeout = timeout
        self.curl = pycurl.Curl()
        self.progressbar = tqdm(unit='B', unit_scale=True, unit_divisor=1024)
        self.progressbar.clear()

    def process_section(self, section: ShowSection, name: str):
        self.logger.info(f'processing section {section}')
        self.logger.debug(f'searching for {name}')
        try:
            video = section.get(name)
        except NotFound:
            self.logger.error(f'unable to find: {name}')
            sys.exit(os.EX_DATAERR)
        self.logger.debug(f'Found: {name}')
        self.video_episodes(video=video)

    def process_playlist(self, playlist: Playlist, remove=False):
        self.logger.info(f'processing playlist {playlist}')
        for video in tqdm(playlist.items(), desc='video count', bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}',
                          disable=not self.show_progress):
            self.logger.debug(f'Video {video.title} from playlist {playlist.title}')
            video.reload()
            self.logger.debug(f'view count: {video.viewCount}')
            self.video_episodes(video=video)
            if remove:
                logging.info(f'deleting {video.title} from playlist')
                playlist.removeItem(video)

    def video_episodes(self, video: Video):
        if video.type == 'show':
            self.logger.debug(f'Found Show: {video.title}')
            for episode in tqdm(video.episodes(), desc='video count', bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}',
                                disable=not self.show_progress):
                episode.reload()
                self.logger.debug(f'Found: {episode.season().title} Episode {episode.index} {episode.title}')
                self.logger.debug(f'view count: {episode.viewCount}')
                self.video_parts(video=episode)
        else:
            self.logger.info(f'Found: {video.title}')
            self.video_parts(video=video)

    def curl_progress(self, download_total: int, downloaded: int, upload_total: int, uploaded: int):
        self.progressbar.total = download_total
        self.progressbar.n = downloaded
        self.progressbar.update()

    def video_parts(self, video: Video):
        self.logger.debug(f'finding parts for {video}')
        for part in video.iterParts():
            self.logger.debug(f'Found: {part.id} {part.file}')
            self.logger.info(f'mkdir: {os.path.dirname(os.path.abspath(self.target + part.file))}')
            path = os.path.dirname(os.path.abspath(self.target + part.file))
            filename = os.path.basename(os.path.abspath(self.target + part.file))
            url = f'{video.url(part.key)}&download=1'
            self.logger.info(f'downloading {url} to {path + "/." + filename}')
            if video.viewCount == 0 or self.force:
                status = self.download(url=url, path=path, filename=filename, title=video.title)
                if status in [200, 416]:
                    pass
                elif status in [403] and not self.no_transcoding:
                    # try downloading via transcode
                    self.logger.warning('trying download via transcoding.')
                    status = self.download(url=video.getStreamURL(), path=path, filename=filename, title=video.title, resume=False)
                    if status not in [200, 416]:
                        continue
                else:
                    continue
                if self.assets:
                    self.download_subtitles(video=video, part=part, path=path, filename=filename)
                    self.download_pics(video=video, path=path, filename=filename)
                self.logger.info(f'marking {video.title} as watched')
                video.markWatched()
            elif self.refresh_assets:
                self.download_subtitles(video=video, part=part, path=path, filename=filename)
                self.download_pics(video=video, path=path, filename=filename)
            else:
                self.logger.info(f'{video.title} already seen')

    def download_subtitles(self, video: Video, part: MediaPart, path: str, filename: str):
        self.logger.debug(f'downloading subtitles for {part}')
        for sub in part.subtitleStreams():
            self.logger.debug(f'Found subtitle {sub}')
            if sub.key is None:
                self.logger.debug('Subtitle is embedded, skipping')
                continue
            sub_filename = f'{".".join(filename.split(".")[0:-1])}.{sub.languageCode}.{sub.codec}'
            url = video.url(sub.key)
            self.download(url=url, path=path, filename=sub_filename, title=f'{sub.languageCode} {sub.codec}', resume=False)

    def download_pics(self, video: Video, path: str, filename: str):
        self.logger.debug(f'downloading pics for {video}')
        artfilename = f'{".".join(filename.split(".")[0:-1])}-{"fanart"}.{"jpg"}'
        self.download(url=video.artUrl, path=path, filename=artfilename, title='thumbnail', resume=False)
        thumbfilename = f'{".".join(filename.split(".")[0:-1])}.{"jpg"}'
        self.download(url=video.thumbUrl, path=path, filename=thumbfilename, title='art', resume=False)

    def download(self, url: str, path: str, filename: str, title: str, resume: bool = True) -> int:
        self.logger.debug(f'downloading {url} {path} {filename} {title} {resume}')
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
        except Exception as e:
            self.logger.fatal(f'Unexpected error: {repr(e)}')
            sys.exit(os.EX_CANTCREAT)
        self.curl.setopt(self.curl.URL, url)
        if self.bw_limit:
            self.curl.setopt(self.curl.MAX_RECV_SPEED_LARGE, self.bw_limit)
        if os.path.exists(path + "/." + filename) and resume:
            file_id = open(path + "/." + filename, "ab")
            self.curl.setopt(self.curl.RESUME_FROM, os.path.getsize(path + "/." + filename))
        else:
            try:
                os.unlink(path + "/." + filename)
            except FileNotFoundError:
                pass
            file_id = open(path + "/." + filename, "xb")
            self.curl.setopt(self.curl.RESUME_FROM, 0)
        self.curl.setopt(self.curl.WRITEDATA, file_id)
        self.logger.debug(f'timeout: {self.timeout}')
        self.curl.setopt(self.curl.TIMEOUT, self.timeout)
        if self.show_progress:
            self.progressbar.set_description(desc=f'Downloading {title}')
            self.progressbar.reset()
            self.curl.setopt(self.curl.NOPROGRESS, 0)
            self.curl.setopt(self.curl.XFERINFOFUNCTION, self.curl_progress)
        else:
            self.curl.setopt(self.curl.NOPROGRESS, 1)
        try:
            self.curl.perform()
        except pycurl.error as e:
            self.logger.warning(f"{e.args[0]} {e.args[1]}")
            if e.args[0] == 33 and resume is True:
                self.logger.warning("server doesn't support resume, therefore retrying without.")
                return self.download(url=url, path=path, filename=filename, title=title, resume=False)
            return e.args[0]
        response_code = self.curl.getinfo(self.curl.RESPONSE_CODE)
        self.progressbar.clear()
        self.logger.debug(f'response code: {response_code}')
        if response_code in [200, 416]:
            self.logger.info(f'renaming {path + "/." + filename} to {path + "/" + filename}')
            os.rename(path + "/." + filename, path + "/" + filename)
        elif response_code == 403:
            self.logger.warning(f'Error downloading "{title}" got response code: {response_code}')
            self.logger.warning(f'Hint: Server needs Plex Pass and need to have downloads allowed.')
            os.unlink(path + "/." + filename)
        else:
            self.logger.error(f'Error downloading "{title}" got response code: {response_code}')
            os.unlink(path + "/." + filename)
        return response_code


class MyFormatter(logging.Formatter):
    def __init__(self, token: str):
        super().__init__(fmt='%(asctime)s %(levelname)-8s %(filename)s:%(lineno)d:%(funcName)-18s %(message)s')
        self.token = token

    def format(self, record):
        if self.token in record.msg:
            record.msg = record.msg.replace(self.token, "XXX")
        return super().format(record)


if __name__ == "__main__":
    logger = logging.getLogger('download')
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(filename)s:%(lineno)d:%(funcName)-18s %(message)s'))
    logger.addHandler(log_handler)

    authentication = netrc.netrc().authenticators('plex')
    if authentication is None:
        logger.error("can't find machine 'plex' in your ~/.netrc")
        sys.exit(os.EX_NOTFOUND)
    user = MyPlexAccount(authentication[0], authentication[2])

    parser = argparse.ArgumentParser()
    group1 = parser.add_mutually_exclusive_group()
    group1.add_argument("-d", "--debug", action="store_true")
    group1.add_argument("-v", "--verbose", action="store_true")
    group1.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--server", help="Plex server name to fetch files from", required=True,
                        choices=[x.name for x in user.resources() if x.provides == 'server'])
    parser.add_argument("--target", help="destination folder", required=True)
    parser.add_argument("--section", help="section to fetch")
    parser.add_argument("--name", help="movie or series to fetch")
    parser.add_argument("--bwlimit", help="limit bandwidth in bytes/s", type=int)
    parser.add_argument("--progress", help="show download progress", action="store_true")
    parser.add_argument("--force", help="force download, even if already seen", action="store_true")
    parser.add_argument("--assets", help="also download other assets (subtitles, cover and fanart)", action="store_true")
    parser.add_argument("--refresh-assets", help="redownload all assets", action="store_true")
    parser.add_argument("--no-transcoding", help="deny transcoding if direct download fail", action="store_true")
    parser.add_argument("--timeout", help="timeout in seconds", type=int, default=300)
    playlist_group = parser.add_argument_group()
    playlist_group.add_argument("--playlist", help="playlist to fetch")
    playlist_group.add_argument("--playlist-remove", action="store_true", help="cleanup playlist after downloading")
    args = parser.parse_args()

    if not (args.playlist or args.section) or (args.playlist and args.section):
        parser.error('either --section or --playlist required')
    elif args.name and not args.section:
        parser.error('--name specified without --section')
    if args.debug:
        loglevel = logging.DEBUG
    elif args.verbose:
        loglevel = logging.INFO
    elif args.quiet:
        loglevel = logging.ERROR
    else:
        loglevel = logging.WARNING
    logger.setLevel(loglevel)

    logger.info(f'connecting to {args.server}')
    plex = user.resource(args.server).connect()
    logger.handlers[0].setFormatter(MyFormatter(token=plex._token))
    pd = PlexDownloader(target=args.target, bw_limit=args.bwlimit, show_progress=args.progress, assets=args.assets, force=args.force,
                        refresh_assets=args.refresh_assets, no_transcoding=args.no_transcoding, timeout=args.timeout)
    if args.section:
        logger.info(f'selecting section {args.section}')
        try:
            se = plex.library.section(args.section)
        except NotFound:
            logger.error(f'section {args.section} not found')
            sys.exit(os.EX_DATAERR)
        pd.process_section(section=se, name=args.name)
    elif args.playlist:
        logger.info(f'selecting playlist {args.playlist}')
        try:
            pl = plex.playlist(args.playlist)
        except NotFound:
            logger.error(f'playlist {args.playlist} not found')
            sys.exit(os.EX_DATAERR)
        pd.process_playlist(playlist=pl, remove=args.playlist_remove)
