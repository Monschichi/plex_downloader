#!/usr/bin/env python3

import argparse
import logging
import netrc
import os
import sys

from plexapi.exceptions import NotFound
from plexapi.myplex import MyPlexAccount


def process_section(section, target, name):
    logger = logging.getLogger('download')
    logger.info('processing section %s' % section)
    logger.debug('searching for %s' % name)
    try:
        video = section.get(name)
    except:
        logger.error('unable to find: %s' % name)
        os._exit(os.EX_DATAERR)
    logger.debug('Found: %s' % name)
    video_episodes(video, target)


def process_playlist(playlist, target, remove=False):
    logger = logging.getLogger('download')
    logger.info('processing playlist %s' % playlist)
    for video in playlist.items():
        logger.debug('Video %s from playlist %s' % (video.title, playlist.title))
        video.reload()
        logger.debug('viewcount: %s' % video.viewCount)
        if video.viewCount > 0:
            logger.info('%s already seen' % video.title)
            continue
        video_episodes(video, target)
        if remove:
            logging.info('deleting %s from playlist' % video.title)
            playlist.removeItem(video)


def video_episodes(video, target):
    logger = logging.getLogger('download')
    if video.type == 'show':
        logger.debug('Found Show: %s' % video.title)
        for episode in video.episodes():
            episode.reload()
            logger.debug('Found: %s episode %s %s' % (episode.season().title, episode.index, episode.title))
            logger.debug('viewcount: %s' % episode.viewCount)
            if episode.viewCount > 0:
                logger.info('%s %s already seen' % (episode.season().title, episode.index))
                continue
            download(episode, target)
            logger.info('marking %s as watched' % episode.title)
            episode.markWatched()
    else:
        logger.info('Found: %s' % video.title)
        download(video, target)
        logger.info('marking %s as watched' % video.title)
        video.markWatched()


def download(video, target):
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
        except:
            logger.fatal('Unexpected error: %s' % sys.exc_info()[0])
            os._exit(os.EX_CANTCREAT)
        url = video._server.url('%s?download=1&X-Plex-Token=%s' % (part.key, video._server._token))
        logger.info('downloading %s to %s' % (url, path + "/." + filename))
        with video._server._session.get(url, stream=True) as r, open(path + "/." + filename, 'wb') as out_file:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:  # filter out keep-alive new chunks
                    out_file.write(chunk)
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
                os._exit(os.EX_DATAERR)
            process_section(section=section, target=args.target, name=args.name)
        elif args.playlist:
            logger.info('selecting playlist %s' % args.playlist)
            try:
                playlist = plex.playlist(args.playlist)
            except NotFound:
                logger.error('playlist %s not found' % args.playlist)
                os._exit(os.EX_DATAERR)
            process_playlist(playlist=playlist, target=args.target, remove=args.playlist_remove)


if __name__ == "__main__":
    main()
