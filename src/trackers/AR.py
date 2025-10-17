# -*- coding: utf-8 -*-
import aiofiles
import aiohttp
import json
import os
import pickle
import platform
import re
import asyncio
import signal
from rich.prompt import Prompt
import urllib.parse
from src.exceptions import *  # noqa F403
from bs4 import BeautifulSoup
from src.console import console
from src.trackers.COMMON import COMMON
from pymediainfo import MediaInfo


class AR():
    def __init__(self, config):
        self.config = config
        self.session = None
        self.tracker = 'AR'
        self.source_flag = 'AlphaRatio'
        self.username = config['TRACKERS']['AR'].get('username', '').strip()
        self.password = config['TRACKERS']['AR'].get('password', '').strip()
        self.base_url = 'https://alpharatio.cc'
        self.login_url = f'{self.base_url}/login.php'
        self.upload_url = f'{self.base_url}/upload.php'
        self.search_url = f'{self.base_url}/torrents.php'
        self.user_agent = f'Upload Assistant/2.3 ({platform.system()} {platform.release()})'
        self.banned_groups = []

    async def get_type(self, meta):

        if (meta['type'] == 'DISC' or meta['type'] == 'REMUX') and meta['source'] == 'Blu-ray':
            return "14"

        if meta.get('anime'):
            if meta['sd']:
                return '15'
            else:
                return {
                    '8640p': '16',
                    '4320p': '16',
                    '2160p': '16',
                    '1440p': '16',
                    '1080p': '16',
                    '1080i': '16',
                    '720p': '16',
                }.get(meta['resolution'], '15')

        elif meta['category'] == "TV":
            if meta['tv_pack']:
                if meta['sd']:
                    return '4'
                else:
                    return {
                        '8640p': '6',
                        '4320p': '6',
                        '2160p': '6',
                        '1440p': '5',
                        '1080p': '5',
                        '1080i': '5',
                        '720p': '5',
                    }.get(meta['resolution'], '4')
            elif meta['sd']:
                return '0'
            else:
                return {
                    '8640p': '2',
                    '4320p': '2',
                    '2160p': '2',
                    '1440p': '1',
                    '1080p': '1',
                    '1080i': '1',
                    '720p': '1',
                }.get(meta['resolution'], '0')

        if meta['category'] == "MOVIE":
            if meta['sd']:
                return '7'
            else:
                return {
                    '8640p': '9',
                    '4320p': '9',
                    '2160p': '9',
                    '1440p': '8',
                    '1080p': '8',
                    '1080i': '8',
                    '720p': '8',
                }.get(meta['resolution'], '7')

    async def start_session(self):
        if self.session is not None:
            console.print("[dim red]Warning: Previous session was not closed properly. Closing it now.")
            await self.close_session()
        self.session = aiohttp.ClientSession()

        self.attach_signal_handlers()
        return aiohttp

    async def close_session(self):
        if self.session is not None:
            await self.session.close()
            self.session = None

    def attach_signal_handlers(self):
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.handle_shutdown(sig)))
            except NotImplementedError:
                pass

    async def handle_shutdown(self, sig):
        console.print(f"[red]Received shutdown signal {sig}. Closing session...[/red]")
        await self.close_session()

    async def validate_credentials(self, meta):
        if self.session:
            console.print("[red dim]Warning: Previous session was not closed properly. Using existing session.")
        else:
            try:
                await self.start_session()
            except asyncio.CancelledError:
                console.print("[red]Session startup interrupted! Cleaning up...[/red]")
                await self.close_session()
                raise

        if await self.load_session(meta):
            response = await self.get_initial_response()
            if await self.validate_login(response):
                return True
        else:
            console.print("[yellow]No session file found. Attempting to log in...")
            if await self.login():
                console.print("[green]Login successful, saving session file.")
                valid = await self.save_session(meta)
                if valid:
                    if meta['debug']:
                        console.print("[blue]Session file saved successfully.")
                    return True
                else:
                    return False
            else:
                console.print('[red]Failed to validate credentials. Please confirm that the site is up and your passkey is valid. Exiting')

        await self.close_session()
        return False

    async def get_initial_response(self):
        async with self.session.get(self.login_url) as response:
            return await response.text()

    async def validate_login(self, response_text):
        if 'login.php?act=recover' in response_text:
            console.print("[red]Login failed. Check your credentials.")
            return False
        return True

    async def login(self):
        data = {
            "username": self.username,
            "password": self.password,
            "keeplogged": "1",
            "login": "Login",
        }
        async with self.session.post(self.login_url, data=data) as response:
            if await self.validate_login(await response.text()):
                return True
        return False

    async def save_session(self, meta):
        try:
            session_file = os.path.abspath(f"{meta['base_dir']}/data/cookies/{self.tracker}.pkl")
            os.makedirs(os.path.dirname(session_file), exist_ok=True)
            cookies = self.session.cookie_jar
            cookie_dict = {}
            for cookie in cookies:
                cookie_dict[cookie.key] = cookie.value

            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, pickle.dumps, cookie_dict)
            async with aiofiles.open(session_file, 'wb') as f:
                await f.write(data)
        except Exception as e:
            console.print(f"[red]Error saving session: {e}[/red]")
            return False

    async def load_session(self, meta):
        session_file = os.path.abspath(f"{meta['base_dir']}/data/cookies/{self.tracker}.pkl")
        retry_count = 0
        max_retries = 2

        while retry_count < max_retries:
            try:
                if not os.path.exists(session_file):
                    console.print(f"[red]Session file not found: {session_file}[/red]")
                    return False  # No session file to load

                loop = asyncio.get_running_loop()
                async with aiofiles.open(session_file, 'rb') as f:
                    data = await f.read()
                    try:
                        cookie_dict = await loop.run_in_executor(None, pickle.loads, data)
                    except (EOFError, pickle.UnpicklingError) as e:
                        console.print(f"[red]Error loading session cookies: {e}[/red]")
                        return False  # Corrupted session file

                if self.session is None:
                    await self.start_session()

                for name, value in cookie_dict.items():
                    self.session.cookie_jar.update_cookies({name: value})

                try:
                    async with self.session.get(f'{self.base_url}/torrents.php', timeout=10) as response:
                        if response.status == 200:
                            console.print("[green]Session validated successfully.[/green]")
                            return True  # Session is valid
                        else:
                            console.print(f"[yellow]Session validation failed with status {response.status}, retrying...[/yellow]")

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    console.print(f"[yellow]Session might be invalid: {e}. Retrying...[/yellow]")

            except (FileNotFoundError, EOFError, pickle.UnpicklingError) as e:
                console.print(f"[red]Session loading error: {e}. Closing session and retrying.[/red]")

            await self.close_session()
            await self.start_session()
            retry_count += 1

        console.print("[red]Failed to reuse session after retries. Either try again or delete the cookie.[/red]")
        return False

    def get_links(self, movie, subheading, heading_end):
        description = ""
        description += "\n" + subheading + "Links" + heading_end + "\n"
        if 'IMAGES' in self.config:
            if movie['imdb_id'] != 0:
                description += f"[URL={movie.get('imdb_info', {}).get('imdb_url', '')}][img]{self.config['IMAGES']['imdb_75']}[/img][/URL]"
            if movie['tmdb'] != 0:
                description += f" [URL=https://www.themoviedb.org/{str(movie['category'].lower())}/{str(movie['tmdb'])}][img]{self.config['IMAGES']['tmdb_75']}[/img][/URL]"
            if movie['tvdb_id'] != 0:
                description += f" [URL=https://www.thetvdb.com/?id={str(movie['tvdb_id'])}&tab=series][img]{self.config['IMAGES']['tvdb_75']}[/img][/URL]"
            if movie['tvmaze_id'] != 0:
                description += f" [URL=https://www.tvmaze.com/shows/{str(movie['tvmaze_id'])}][img]{self.config['IMAGES']['tvmaze_75']}[/img][/URL]"
            if movie['mal_id'] != 0:
                description += f" [URL=https://myanimelist.net/anime/{str(movie['mal_id'])}][img]{self.config['IMAGES']['mal_75']}[/img][/URL]"
        else:
            if movie['imdb_id'] != 0:
                description += f"{movie.get('imdb_info', {}).get('imdb_url', '')}"
            if movie['tmdb'] != 0:
                description += f"\nhttps://www.themoviedb.org/{str(movie['category'].lower())}/{str(movie['tmdb'])}"
            if movie['tvdb_id'] != 0:
                description += f"\nhttps://www.thetvdb.com/?id={str(movie['tvdb_id'])}&tab=series"
            if movie['tvmaze_id'] != 0:
                description += f"\nhttps://www.tvmaze.com/shows/{str(movie['tvmaze_id'])}"
            if movie['mal_id'] != 0:
                description += f"\nhttps://myanimelist.net/anime/{str(movie['mal_id'])}"
        return description

    async def edit_desc(self, meta):
        heading = "[COLOR=GREEN][size=6]"
        subheading = "[COLOR=RED][size=4]"
        heading_end = "[/size][/COLOR]"
        async with aiofiles.open(f"{meta['base_dir']}/tmp/{meta['uuid']}/DESCRIPTION.txt", 'r', encoding='utf8') as f:
            base = await f.read()
        base = re.sub(r'\[center\]\[spoiler=Scene NFO:\].*?\[/center\]', '', base, flags=re.DOTALL)
        base = re.sub(r'\[center\]\[spoiler=FraMeSToR NFO:\].*?\[/center\]', '', base, flags=re.DOTALL)
        with open(f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}]DESCRIPTION.txt", 'w', encoding='utf8') as descfile:
            description = ""
            if meta['is_disc'] == "BDMV":
                description += heading + str(meta['name']) + heading_end + "\n" + self.get_links(meta, subheading, heading_end) + "\n\n" + subheading + "BDINFO" + heading_end + "\n"
            else:
                description += heading + str(meta['name']) + heading_end + "\n" + self.get_links(meta, subheading, heading_end) + "\n\n" + subheading + "MEDIAINFO" + heading_end + "\n"
            if meta.get('discs', []) != []:
                discs = meta['discs']
                if len(discs) >= 2:
                    for each in discs[1:]:
                        if each['type'] == "BDMV":
                            description += f"[hide={each.get('name', 'BDINFO')}][code]{each['summary']}[/code][/hide]\n\n"
                        if each['type'] == "DVD":
                            description += f"{each['name']}:\n"
                            description += f"[hide={os.path.basename(each['vob'])}][code][{each['vob_mi']}[/code][/hide] [hide={os.path.basename(each['ifo'])}][code][{each['ifo_mi']}[/code][/hide]\n\n"
            # description += common.get_links(movie, "[COLOR=red][size=4]", "[/size][/color]")
                elif discs[0]['type'] == "DVD":
                    description += f"[hide][code]{discs[0]['vob_mi']}[/code][/hide]\n\n"
                elif meta['is_disc'] == "BDMV":
                    description += f"[hide][code]{discs[0]['summary']}[/code][/hide]\n\n"
            else:
                # Beautify MediaInfo for AR using custom template
                video = meta['filelist'][0]
                # using custom mediainfo template.
                # can not use full media info as sometimes its more than max chars per post.
                mi_template = os.path.abspath(f"{meta['base_dir']}/data/templates/summary-mediainfo.csv")
                if os.path.exists(mi_template):
                    media_info = await self.parse_mediainfo_async(video, mi_template)
                    description += (f"""[code]\n{media_info}\n[/code]\n""")
                    # adding full mediainfo as spoiler
                    async with aiofiles.open(f"{meta['base_dir']}/tmp/{meta['uuid']}/MEDIAINFO_CLEANPATH.txt", 'r', encoding='utf-8') as MI:
                        full_mediainfo = await MI.read()
                    description += f"[hide=FULL MEDIAINFO][code]{full_mediainfo}[/code][/hide]\n"
                else:
                    console.print("[bold red]Couldn't find the MediaInfo template")
                    console.print("[green]Using normal MediaInfo for the description.")

                    async with aiofiles.open(f"{meta['base_dir']}/tmp/{meta['uuid']}/MEDIAINFO_CLEANPATH.txt", 'r', encoding='utf-8') as MI:
                        cleaned_mediainfo = await MI.read()
                        description += (f"""[code]\n{cleaned_mediainfo}\n[/code]\n\n""")

            description += "\n\n" + subheading + "PLOT" + heading_end + "\n" + str(meta['overview'])
            if meta['genres']:
                description += "\n\n" + subheading + "Genres" + heading_end + "\n" + str(meta['genres'])

            if meta['image_list'] is not None and len(meta['image_list']) > 0:
                description += "\n\n" + subheading + "Screenshots" + heading_end + "\n"
                description += "[align=center]"
                for image in meta['image_list']:
                    if image['raw_url'] is not None:
                        description += "[url=" + image['raw_url'] + "][img]" + image['img_url'] + "[/img][/url]"
                description += "[/align]"
            if 'youtube' in meta:
                description += "\n\n" + subheading + "Youtube" + heading_end + "\n" + str(meta['youtube'])

            # adding extra description if passed
            if len(base) > 2:
                description += "\n\n" + subheading + "Notes" + heading_end + "\n" + str(base)

        async with aiofiles.open(f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}]DESCRIPTION.txt", 'w', encoding='utf8') as descfile:
            await descfile.write(description)
        return

    async def get_language_tag(self, meta):
        lang_tag = ""
        has_eng_audio = False
        audio_lang = ""
        if meta['is_disc'] != "BDMV":
            try:
                async with aiofiles.open(f"{meta.get('base_dir')}/tmp/{meta.get('uuid')}/MediaInfo.json", 'r', encoding='utf-8') as f:
                    mi_content = await f.read()
                    mi = json.loads(mi_content)
                for track in mi['media']['track']:
                    if track['@type'] == "Audio":
                        if track.get('Language', 'None').startswith('en'):
                            has_eng_audio = True
                        if not has_eng_audio:
                            audio_lang = mi['media']['track'][2].get('Language_String', "").upper()
            except Exception as e:
                console.print(f"[red]Error: {e}")
        else:
            for audio in meta['bdinfo']['audio']:
                if audio['language'] == 'English':
                    has_eng_audio = True
                if not has_eng_audio:
                    audio_lang = meta['bdinfo']['audio'][0]['language'].upper()
        if audio_lang != "":
            lang_tag = audio_lang
        return lang_tag

    async def get_basename(self, meta):
        path = next(iter(meta['filelist']), meta['path'])
        return os.path.basename(path)

    async def search_existing(self, meta, DISCTYPE):
        dupes = {}

        # Combine title and year
        title = str(meta.get('title', '')).strip()
        year = str(meta.get('year', '')).strip()
        if not title:
            await self.close_session()
            console.print("[red]Title is missing.")
            return dupes

        search_query = f"{title} {year}".strip()  # Concatenate title and year
        search_query_encoded = urllib.parse.quote(search_query)

        search_url = f'{self.base_url}/ajax.php?action=browse&searchstr={search_query_encoded}'

        if meta.get('debug', False):
            console.print(f"[blue]{search_url}")

        try:
            async with self.session.get(search_url) as response:
                if response.status != 200:
                    await self.close_session()
                    console.print("[bold red]Request failed. Site May be down")
                    return dupes

                json_response = await response.json()
                if json_response.get('status') != 'success':
                    await self.close_session()
                    console.print("[red]Invalid response status.")
                    return dupes

                results = json_response.get('response', {}).get('results', [])
                if not results:
                    await self.close_session()
                    return dupes

                dupes = []
                for res in results:
                    if 'groupName' in res:
                        dupe = {
                            'name': res['groupName'],
                            'size': res['size'],
                            'files': res['groupName'],
                            'file_count': res['fileCount'],
                            'link': f'{self.search_url}?id={res["groupId"]}&torrentid={res["torrentId"]}',
                        }
                        dupes.append(dupe)

                await self.close_session()
                return dupes

        except Exception as e:
            console.print(f"[red]Error occurred: {e}")

        if meta['debug']:
            console.print(f"[blue]{dupes}")
        await self.close_session()
        return dupes

    def _has_existing_torrents(self, response_text):
        """Check the response text for existing torrents."""
        return 'Your search did not match anything.' not in response_text

    def extract_auth_key(self, response_text):
        soup = BeautifulSoup(response_text, 'html.parser')
        logout_link = soup.find('a', href=True, text='Logout')

        if logout_link:
            href = logout_link['href']
            match = re.search(r'auth=([^&]+)', href)
            if match:
                return match.group(1)
        return None

    async def upload(self, meta, disctype):
        try:
            # Prepare the data for the upload
            common = COMMON(config=self.config)
            await common.edit_torrent(meta, self.tracker, self.source_flag)
            await self.edit_desc(meta)
            type = await self.get_type(meta)
            # Read the description
            desc_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}]DESCRIPTION.txt"
            try:
                async with aiofiles.open(desc_path, 'r', encoding='utf-8') as desc_file:
                    desc = await desc_file.read()
            except FileNotFoundError:
                raise Exception(f"Description file not found at {desc_path} ")

            # Handle cover image input
            cover = meta.get('poster', None) or meta["imdb_info"].get("cover", None)
            while cover is None and not meta.get("unattended", False):
                cover = Prompt.ask("No Poster was found. Please input a link to a poster:", default="")
                if not re.match(r'https?://.*\.(jpg|png|gif)$', cover):
                    console.print("[red]Invalid image link. Please enter a link that ends with .jpg, .png, or .gif.")
                    cover = None
            # Tag Compilation
            genres = meta.get('genres')
            if genres:
                genres = ', '.join(tag.strip('.') for tag in (item.replace(' ', '.') for item in genres.split(',')))
                genres = re.sub(r'\.{2,}', '.', genres)
            # adding tags
            tags = ""
            if meta['imdb_id'] != 0:
                tags += f"tt{meta.get('imdb', '')}, "
            # no special chars can be used in tags. keep to minimum working tags only.
            tags += f"{genres}, "
            # Get initial response and extract auth key
            initial_response = await self.get_initial_response()
            auth_key = self.extract_auth_key(initial_response)
            # Access the session cookie
            cookies = self.session.cookie_jar.filter_cookies(self.upload_url)
            session_cookie = cookies.get('session')
            if not session_cookie:
                raise Exception("Session cookie not found.")

            # must use scene name if scene release
            KNOWN_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts"}
            if meta['scene']:
                ar_name = meta.get('scene_name')
            else:
                ar_name = meta['uuid']
                base, ext = os.path.splitext(ar_name)
                if ext.lower() in KNOWN_EXTENSIONS:
                    ar_name = base
                ar_name = ar_name.replace(' ', ".").replace("'", '').replace(':', '').replace("(", '.').replace(")", '.').replace("[", '.').replace("]", '.').replace("{", '.').replace("}", '.')
                ar_name = re.sub(r'\.{2,}', '.', ar_name)

            tag_lower = meta['tag'].lower()
            invalid_tags = ["nogrp", "nogroup", "unknown", "-unk-"]
            if meta['tag'] == "" or any(invalid_tag in tag_lower for invalid_tag in invalid_tags):
                for invalid_tag in invalid_tags:
                    ar_name = re.sub(f"-{invalid_tag}", "", ar_name, flags=re.IGNORECASE)
                ar_name = f"{ar_name}-NoGRP"

            data = {
                "submit": "true",
                "auth": auth_key,
                "type": type,
                "title": ar_name,
                "tags": tags,
                "image": cover,
                "desc": desc,
            }

            headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Origin": f'{self.base_url}',
                "Referer": f'{self.base_url}/upload.php',
                "Cookie": f"session={session_cookie.value}",
            }

            torrent_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}].torrent"

            if meta['debug'] is False:
                # Use existing session instead of creating a new one if possible
                upload_session = self.session or None
                try:
                    async with aiofiles.open(torrent_path, 'rb') as torrent_file:
                        torrent_data = await torrent_file.read()

                        # Create a new session only if we don't have one
                        if upload_session is None:
                            async with aiohttp.ClientSession() as session:
                                form = aiohttp.FormData()
                                for key, value in data.items():
                                    form.add_field(key, value)
                                form.add_field('file_input', torrent_data, filename=f"{self.tracker}.torrent")

                                # Perform the upload
                                try:
                                    async with session.post(self.upload_url, data=form, headers=headers) as response:
                                        await asyncio.sleep(1)  # Give some time for the upload to process
                                        await self._handle_upload_response(response, meta, data)
                                except Exception:
                                    await self.close_session()
                                    meta['tracker_status'][self.tracker]['status_message'] = "data error - AR it may have uploaded, go check"
                                    return
                        else:
                            # Use existing session
                            form = aiohttp.FormData()
                            for key, value in data.items():
                                form.add_field(key, value)
                            form.add_field('file_input', torrent_data, filename=f"{self.tracker}.torrent")
                            # Perform the upload
                            try:
                                async with upload_session.post(self.upload_url, data=form, headers=headers) as response:
                                    await asyncio.sleep(1)
                                    await self._handle_upload_response(response, meta, data)
                            except Exception:
                                await self.close_session()
                                meta['tracker_status'][self.tracker]['status_message'] = "data error - AR it may have uploaded, go check"
                                return
                except FileNotFoundError:
                    meta['tracker_status'][self.tracker]['status_message'] = f"data error - AR file not found: {torrent_path}"
                    await self.close_session()
                return
            else:
                await self.close_session()
                console.print("[cyan]AR Request Data:")
                console.print(data)
                meta['tracker_status'][self.tracker]['status_message'] = "Debug mode enabled, not uploading."
        except Exception as e:
            await self.close_session()
            meta['tracker_status'][self.tracker]['status_message'] = f"data error - AR Upload failed: {e}"
            return

    async def _handle_upload_response(self, response, meta, data):
        if response.status == 200:
            # URL format in case of successful upload: https://alpharatio.cc/torrents.php?id=2989202
            console.print(f"[green]{response.url}")
            match = re.match(r".*?alpharatio\.cc/torrents\.php\?id=(\d+)", str(response.url))
            try:
                if match is None:
                    await self.close_session()
                    console.print(response.url)
                    console.print(data)
                    raise UploadException(  # noqa F405
                        f"Upload to {self.tracker} failed: result URL {response.url} ({response.status}) is not the expected one.")  # noqa F405

                # having UA add the torrent link as a comment.
                if match:
                    await self.close_session()
                    common = COMMON(config=self.config)
                    await common.add_tracker_torrent(meta, self.tracker, self.source_flag, self.config['TRACKERS'][self.tracker].get('announce_url'), str(response.url))
            except Exception as e:
                console.print(f"[red]Error: {e}")
                await self.close_session()
                return
        else:
            console.print("[red]Upload failed. Response was not 200.")

    async def parse_mediainfo_async(self, video_path, template_path):
        """Parse MediaInfo asynchronously using thread executor"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: MediaInfo.parse(
                video_path,
                output="STRING",
                full=False,
                mediainfo_options={"inform": f"file://{template_path}"}
            )
        )
