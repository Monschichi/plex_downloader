#!/usr/bin/env python3

import argparse
import logging
import netrc
import os
import sys

import pycurl
from plexapi.exceptions import NotFound
from plexapi.myplex import MyPlexAccount
from tqdm import tqdm

curl = pycurl.Curl()
progressbar = tqdm(unit='B', unit_scale=True, unit_divisor=1024)
progressbar.clear()


def process_section(section, target, name, bwlimit, progress):
    logger = logging.getLogger('download')
    logger.info('processing section %s' % section)
    logger.debug('searching for %s' % name)
    try:
        video = section.get(name)
    except NotFound:
        logger.error('unable to find: %s' % name)
        sys.exit(os.EX_DATAERR)
    logger.debug('Found: %s' % name)
    video_episodes(video=video, target=target, bwlimit=bwlimit, progress=progress)


def process_playlist(playlist, target, bwlimit, progress, remove=False):
    logger = logging.getLogger('download')
    logger.info('processing playlist %s' % playlist)
    for video in playlist.items():
        logger.debug('Video %s from playlist %s' % (video.title, playlist.title))
        video.reload()
        logger.debug('viewcount: %s' % video.viewCount)
        if video.viewCount > 0:
            logger.info('%s already seen' % video.title)
            continue
        video_episodes(video=video, target=target, bwlimit=bwlimit, progress=progress)
        if remove:
            logging.info('deleting %s from playlist' % video.title)
            playlist.removeItem(video)


def video_episodes(video, target, bwlimit, progress):
    logger = logging.getLogger('download')
    if video.type == 'show':
        logger.debug('Found Show: %s' % video.title)
        for episode in video.episodes():
            episode.reload()
            logger.debug('Found: %s Episode %s %s' % (episode.season().title, episode.index, episode.title))
            logger.debug('view count: %s' % episode.viewCount)
            if episode.viewCount > 0:
                logger.info('%s Episode %s already seen' % (episode.season().title, episode.index))
                continue
            download(video=episode, target=target, bwlimit=bwlimit, progress=progress)
            logger.info('marking %s as watched' % episode.title)
            episode.markWatched()
    else:
        logger.info('Found: %s' % video.title)
        download(video=video, target=target, bwlimit=bwlimit, progress=progress)
        logger.info('marking %s as watched' % video.title)
        video.markWatched()


def curl_progress(download_total, downloaded, upload_total, uploaded):
    progressbar.total = download_total
    progressbar.n = downloaded
    progressbar.update()


def download(video, target, bwlimit, progress):
    logger = logging.getLogger('download')
    logger.debug('downloading %s' % video)
    for part in video.iterParts():
        logger.debug('Found: %s %s' % (part.id, part.file))
        logger.info('mkdir: %s' % os.path.dirname(os.path.abspath(target + part.file)))
        path = os.path.dirname(os.path.abspath(target + part.file))
        filename = os.path.basename(os.path.abspath(target + part.file))
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
        except Exception as e:
            logger.fatal('Unexpected error: %s' % repr(e))
            sys.exit(os.EX_CANTCREAT)
        url = video._server.url('%s?download=1&X-Plex-Token=%s' % (part.key, video._server._token))
        logger.info('downloading %s to %s' % (url, path + "/." + filename))
        curl.setopt(curl.URL, url)
        if bwlimit:
            curl.setopt(curl.MAX_RECV_SPEED_LARGE, bwlimit)
        if os.path.exists(path + "/." + filename):
            file_id = open(path + "/." + filename, "ab")
            curl.setopt(curl.RESUME_FROM, os.path.getsize(path + "/." + filename))
        else:
            file_id = open(path + "/." + filename, "wb")

        curl.setopt(curl.WRITEDATA, file_id)
        if progress:
            progressbar.set_description(desc='Downloading %s' % video.title)
            progressbar.reset()
            curl.setopt(curl.NOPROGRESS, 0)
            curl.setopt(curl.XFERINFOFUNCTION, curl_progress)
        else:
            curl.setopt(curl.NOPROGRESS, 1)
        curl.perform()
        progressbar.clear()
        logger.info('renaming %s to %s' % (path + "/." + filename, path + "/" + filename))
        os.rename(path + "/." + filename, path + "/" + filename)


def main():
    logformat = '%(asctime)s %(filename)-18s %(levelname)-8s: %(message)s'
    logger = logging.getLogger('download')
    loghandler = logging.StreamHandler()
    loghandler.setFormatter(logging.Formatter(logformat))
    logger.addHandler(loghandler)
    authentication = netrc.netrc().authenticators('plex')
    if authentication is None:
        logger.error("can't find Machine 'plex' in your ~/.netrc")
    else:
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
        group2 = parser.add_argument_group()
        group2.add_argument("--playlist", help="playlist to fetch")
        group2.add_argument("--playlist-remove", action="store_true", help="cleanup playlist after downloading")
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

        logger.info('connecting to %s' % args.server)
        plex = user.resource(args.server).connect()
        if args.section:
            logger.info('selecting section %s' % args.section)
            try:
                section = plex.library.section(args.section)
            except NotFound:
                logger.error('section %s not found' % args.section)
                sys.exit(os.EX_DATAERR)
            process_section(section=section, target=args.target, name=args.name, bwlimit=args.bwlimit, progress=args.progress)
        elif args.playlist:
            logger.info('selecting playlist %s' % args.playlist)
            try:
                playlist = plex.playlist(args.playlist)
            except NotFound:
                logger.error('playlist %s not found' % args.playlist)
                sys.exit(os.EX_DATAERR)
            process_playlist(playlist=playlist, target=args.target, remove=args.playlist_remove, bwlimit=args.bwlimit,
                             progress=args.progress)


if __name__ == "__main__":
    main()
