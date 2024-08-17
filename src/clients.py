# -*- coding: utf-8 -*-
from torf import Torrent
import xmlrpc.client
import bencode
import os
import qbittorrentapi
from deluge_client import DelugeRPCClient, LocalDelugeRPCClient
import base64
from pyrobase.parts import Bunch
import errno
import asyncio
import ssl
import shutil
import time


from src.console import console 



class Clients():
    """
    Add to torrent client
    """
    def __init__(self, config):
        self.config = config
        pass
    

    async def add_to_client(self, meta, tracker):
        torrent_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/[{tracker}]{meta['clean_name']}.torrent"
        if meta.get('no_seed', False) == True:
            console.print(f"[bold red]--no-seed was passed, so the torrent will not be added to the client")
            console.print(f"[bold yellow]Add torrent manually to the client")
            return
        if os.path.exists(torrent_path):
            torrent = Torrent.read(torrent_path)
        else:
            return
        if meta.get('client', None) == None:
            default_torrent_client = self.config['DEFAULT']['default_torrent_client']
        else:
            default_torrent_client = meta['client']
        if meta.get('client', None) == 'none':
            return
        if default_torrent_client == "none":
            return 
        client = self.config['TORRENT_CLIENTS'][default_torrent_client]
        torrent_client = client['torrent_client']
        
        local_path, remote_path = await self.remote_path_map(meta)
        
        console.print(f"[bold green]Adding to {torrent_client}")
        if torrent_client.lower() == "rtorrent":
            self.rtorrent(meta['path'], torrent_path, torrent, meta, local_path, remote_path, client)
        elif torrent_client == "qbit":
            await self.qbittorrent(meta['path'], torrent, local_path, remote_path, client, meta['is_disc'], meta['filelist'], meta)
        elif torrent_client.lower() == "deluge":
            if meta['type'] == "DISC":
                path = os.path.dirname(meta['path'])
            self.deluge(meta['path'], torrent_path, torrent, local_path, remote_path, client, meta)
        elif torrent_client.lower() == "watch":
            shutil.copy(torrent_path, client['watch_folder'])
        return
   
        

    async def find_existing_torrent(self, meta):
        default_torrent_client = meta.get('client') or self.config['DEFAULT']['default_torrent_client']
        
        if default_torrent_client == 'none':
            return None
        
        client = self.config['TORRENT_CLIENTS'].get(default_torrent_client)
        torrent_storage_dir = client.get('torrent_storage_dir')
        torrent_client = client.get('torrent_client', '').lower()
        
        if torrent_storage_dir is None and torrent_client != "watch":
            console.print(f'[bold red]Missing torrent_storage_dir for {default_torrent_client}')
            return None
        elif not os.path.exists(str(torrent_storage_dir)) and torrent_client != "watch":
            if meta.get('debug'):
                console.log(f"[debug] Checking directory existence: {torrent_storage_dir}")
            console.print(f"[bold red]Invalid torrent_storage_dir path: [bold yellow]{torrent_storage_dir}")
            return None

        torrenthash = meta.get('torrenthash') or meta.get('ext_torrenthash')
        if torrenthash and os.path.exists(torrent_storage_dir):
            if meta.get('debug'):
                console.log(f"[debug] Checking torrent file existence: {torrent_storage_dir}/{torrenthash}.torrent")
            torrent_path = f"{torrent_storage_dir}/{torrenthash}.torrent"
            valid, torrent_path = await self.is_valid_torrent(meta, torrent_path, torrenthash, torrent_client, print_err=True)
            if valid:
                return torrent_path
        
        if torrent_client == 'qbit' and client.get('enable_search'):
            torrenthash = await self.search_qbit_for_torrent(meta, client)
            if torrenthash:
                torrent_path = f"{torrent_storage_dir}/{torrenthash}.torrent"
                valid2, torrent_path = await self.is_valid_torrent(meta, torrent_path, torrenthash, torrent_client, print_err=False)
                if valid2:
                    return torrent_path
        
        console.print("[bold yellow]No Valid .torrent found")
        return None


    async def is_valid_torrent(self, meta, torrent_path, torrenthash, torrent_client, print_err=False):
        torrenthash = torrenthash.lower().strip() if torrent_client in ('qbit', 'deluge') else torrenthash.upper().strip()
        torrent_path = torrent_path.replace(torrenthash.upper(), torrenthash)
        
        if meta.get('debug'):
            console.log(f"[debug] Checking torrent path: {torrent_path}")
        
        if not os.path.exists(torrent_path):
            console.print(f'[bold yellow]{torrent_path} was not found')
            return False, torrent_path

        torrent = Torrent.read(torrent_path)
        valid = await self.check_torrent_validity(meta, torrent)
        wrong_file = self.check_wrong_file(meta, torrent)
        
        if valid:
            valid = not self.check_piece_constraints(torrent)
            if valid and not wrong_file:
                console.print(f'[bold green]REUSING .torrent with infohash: [bold yellow]{torrenthash}')
            else:
                valid = False
        else:
            console.print('[bold yellow]Unwanted Files/Folders Identified')
        
        if wrong_file:
            console.print("[bold red] Provided .torrent has files that were not expected")
        
        if print_err and not valid:
            console.print("[bold yellow]Too many pieces exist or other validation failed. REHASHING")
        
        return valid, torrent_path

    async def check_torrent_validity(self, meta, torrent):
        # Check if the torrent matches the expected metadata
        if meta.get('is_disc'):
            return os.path.basename(meta['path']) in os.path.commonpath(torrent.files)
        
        if len(torrent.files) == len(meta['filelist']) == 1:
            return os.path.basename(torrent.files[0]) == os.path.basename(meta['filelist'][0]) and str(torrent.files[0]) == os.path.basename(torrent.files[0])
        
        if len(torrent.files) == len(meta['filelist']):
            torrent_filepath = os.path.commonpath(torrent.files)
            actual_filepath = os.path.commonpath(meta['filelist'])
            local_path, remote_path = await self.remote_path_map(meta)
            if local_path.lower() in meta['path'].lower() and local_path.lower() != remote_path.lower():
                actual_filepath = torrent_filepath.replace(local_path, remote_path)
                actual_filepath = actual_filepath.replace(os.sep, '/')
            if meta.get('debug'):
                console.log(f"torrent_filepath: {torrent_filepath}")
                console.log(f"actual_filepath: {actual_filepath}")
            return torrent_filepath in actual_filepath
        
        return False

    def check_wrong_file(self, meta, torrent):
        # Check if the torrent contains unexpected files
        if len(torrent.files) == len(meta['filelist']) == 1:
            return os.path.basename(torrent.files[0]) != os.path.basename(meta['filelist'][0])
        return False

    def check_piece_constraints(self, torrent):
        # Check piece constraints to decide if the torrent is reusable
        if (torrent.pieces >= 7000 and torrent.piece_size < 8388608) or (torrent.pieces >= 4000 and torrent.piece_size < 4194304):
            return True
        if torrent.piece_size < 32768:
            return True
        return False


    async def search_qbit_for_torrent(self, meta, client):
        console.print("[green]Searching qbittorrent for an existing .torrent")
        torrent_storage_dir = client.get('torrent_storage_dir')
        
        if not torrent_storage_dir and client.get("torrent_client") != "watch":
            console.print(f"[bold red]Missing torrent_storage_dir for {self.config['DEFAULT']['default_torrent_client']}")
            return None

        try:
            qbt_client = qbittorrentapi.Client(
                host=client['qbit_url'], 
                port=client['qbit_port'], 
                username=client['qbit_user'], 
                password=client['qbit_pass'], 
                VERIFY_WEBUI_CERTIFICATE=client.get('VERIFY_WEBUI_CERTIFICATE', True)
            )
            if meta.get('debug'):
                console.log("[debug] Attempting to log in to qBittorrent API")
            qbt_client.auth_log_in()
            if meta.get('debug'):
                console.log("[debug] qBittorrent API login successful")
        except (qbittorrentapi.LoginFailed, qbittorrentapi.APIConnectionError) as e:
            console.print(f"[bold red]Error connecting to qBittorrent: {str(e)}")
            if meta.get('debug'):
                console.log(f"[debug] API error: {str(e)}")
            return None
        except Exception as e:
            console.print(f"[bold red]Unexpected error during qBittorrent connection: {str(e)}")
            if meta.get('debug'):
                console.log(f"[debug] Unexpected error: {str(e)}")
            return None

        remote_path_map, local_path, remote_path = await self.handle_remote_path_mapping(meta)

        try:
            torrents = qbt_client.torrents.info()
            for torrent in torrents:
                torrent_path = self.get_torrent_path(torrent, meta, remote_path_map, local_path, remote_path)
                if torrent_path and await self.is_matching_torrent(meta, torrent, torrent_path, torrent_storage_dir):
                    return torrent.hash
        except Exception as e:
            console.print(f"[bold red]Unexpected error during torrent search: {str(e)}")
            if meta.get('debug'):
                console.log(f"[debug] Error during torrent search: {str(e)}")
                console.print_exception()

        return None

    async def handle_remote_path_mapping(self, meta):
        remote_path_map = False
        local_path, remote_path = await self.remote_path_map(meta)
        if local_path.lower() in meta['path'].lower() and local_path.lower() != remote_path.lower():
            remote_path_map = True
        return remote_path_map, local_path, remote_path

    def get_torrent_path(self, torrent, meta, remote_path_map, local_path, remote_path):
        try:
            torrent_path = torrent.get('content_path', f"{torrent.save_path}{torrent.name}")
        except AttributeError:
            if meta.get('debug'):
                console.print(torrent)
                console.print_exception()
            return None
        
        if remote_path_map:
            torrent_path = torrent_path.replace(remote_path, local_path)
            torrent_path = torrent_path.replace(os.sep, '/').replace('/', os.sep)
        
        return torrent_path

    async def is_matching_torrent(self, meta, torrent, torrent_path, torrent_storage_dir):
        if meta['is_disc'] in ("", None) and len(meta['filelist']) == 1:
            if torrent_path == meta['filelist'][0] and len(torrent.files) == len(meta['filelist']):
                return await self.verify_torrent(meta, torrent, torrent_storage_dir)
        elif meta['path'] == torrent_path:
            return await self.verify_torrent(meta, torrent, torrent_storage_dir)
        return False

    async def verify_torrent(self, meta, torrent, torrent_storage_dir):
        valid, torrent_path = await self.is_valid_torrent(meta, f"{torrent_storage_dir}/{torrent.hash}.torrent", torrent.hash, 'qbit', print_err=False)
        if valid:
            console.print(f"[green]Found a matching .torrent with hash: [bold yellow]{torrent.hash}")
            return True
        return False

    def rtorrent(self, path, torrent_path, torrent, meta, local_path, remote_path, client):
        rtorrent = xmlrpc.client.Server(client['rtorrent_url'], context=ssl._create_stdlib_context())
        metainfo = bencode.bread(torrent_path)
        try:
            fast_resume = self.add_fast_resume(metainfo, path, torrent)
        except EnvironmentError as exc:
            console.print("[red]Error making fast-resume data (%s)" % (exc,))
            raise
        
            
        new_meta = bencode.bencode(fast_resume)
        if new_meta != metainfo:
            fr_file = torrent_path.replace('.torrent', '-resume.torrent')
            console.print("Creating fast resume")
            bencode.bwrite(fast_resume, fr_file)


        isdir = os.path.isdir(path)
        # if meta['type'] == "DISC":
        #     path = os.path.dirname(path)
        #Remote path mount
        modified_fr = False
        if local_path.lower() in path.lower() and local_path.lower() != remote_path.lower():
            path_dir = os.path.dirname(path)
            path = path.replace(local_path, remote_path)
            path = path.replace(os.sep, '/')
            shutil.copy(fr_file, f"{path_dir}/fr.torrent")
            fr_file = f"{os.path.dirname(path)}/fr.torrent"
            modified_fr = True
        if isdir == False:
            path = os.path.dirname(path)
        
        
        console.print("[bold yellow]Adding and starting torrent")
        rtorrent.load.start_verbose('', fr_file, f"d.directory_base.set={path}")
        time.sleep(1)
        # Add labels
        if client.get('rtorrent_label', None) != None:
            rtorrent.d.custom1.set(torrent.infohash, client['rtorrent_label'])
        if meta.get('rtorrent_label') != None:
            rtorrent.d.custom1.set(torrent.infohash, meta['rtorrent_label'])

        # Delete modified fr_file location
        if modified_fr:
            os.remove(f"{path_dir}/fr.torrent")
        if meta['debug']:
            console.print(f"[cyan]Path: {path}")
        return


    async def qbittorrent(self, path, torrent, local_path, remote_path, client, is_disc, filelist, meta):
        # infohash = torrent.infohash
        #Remote path mount
        isdir = os.path.isdir(path)
        if not isdir and len(filelist) == 1:
            path = os.path.dirname(path)
        if len(filelist) != 1:
            path = os.path.dirname(path)
        if local_path.lower() in path.lower() and local_path.lower() != remote_path.lower():
            path = path.replace(local_path, remote_path)
            path = path.replace(os.sep, '/')
        if not path.endswith(os.sep):
            path = f"{path}/"
        qbt_client = qbittorrentapi.Client(host=client['qbit_url'], port=client['qbit_port'], username=client['qbit_user'], password=client['qbit_pass'], VERIFY_WEBUI_CERTIFICATE=client.get('VERIFY_WEBUI_CERTIFICATE', True))
        console.print("[bold yellow]Adding and rechecking torrent")
        try:
            qbt_client.auth_log_in()
        except qbittorrentapi.LoginFailed:
            console.print("[bold red]INCORRECT QBIT LOGIN CREDENTIALS")
            return
        auto_management = False
        am_config = client.get('automatic_management_paths', '')
        if isinstance(am_config, list):
            for each in am_config:
                if os.path.normpath(each).lower() in os.path.normpath(path).lower(): 
                    auto_management = True
        else:
            if os.path.normpath(am_config).lower() in os.path.normpath(path).lower() and am_config.strip() != "": 
                auto_management = True
        qbt_category = client.get("qbit_cat") if not meta.get("qbit_cat") else meta.get('qbit_cat')

        content_layout = client.get('content_layout', 'Original')
        
        qbt_client.torrents_add(torrent_files=torrent.dump(), save_path=path, use_auto_torrent_management=auto_management, is_skip_checking=True, content_layout=content_layout, category=qbt_category)
        # Wait for up to 30 seconds for qbit to actually return the download
        # there's an async race conditiion within qbt that it will return ok before the torrent is actually added
        for _ in range(0, 30):
            if len(qbt_client.torrents_info(torrent_hashes=torrent.infohash)) > 0:
                break
            await asyncio.sleep(1)
        qbt_client.torrents_resume(torrent.infohash)
        if client.get('qbit_tag', None) != None:
            qbt_client.torrents_add_tags(tags=client.get('qbit_tag'), torrent_hashes=torrent.infohash)
        if meta.get('qbit_tag') != None:
            qbt_client.torrents_add_tags(tags=meta.get('qbit_tag'), torrent_hashes=torrent.infohash)
        console.print(f"Added to: {path}")
        


    def deluge(self, path, torrent_path, torrent, local_path, remote_path, client, meta):
        client = DelugeRPCClient(client['deluge_url'], int(client['deluge_port']), client['deluge_user'], client['deluge_pass'])
        # client = LocalDelugeRPCClient()
        client.connect()
        if client.connected == True:
            console.print("Connected to Deluge")    
            isdir = os.path.isdir(path)
            #Remote path mount
            if local_path.lower() in path.lower() and local_path.lower() != remote_path.lower():
                path = path.replace(local_path, remote_path)
                path = path.replace(os.sep, '/')
            
            path = os.path.dirname(path)

            client.call('core.add_torrent_file', torrent_path, base64.b64encode(torrent.dump()), {'download_location' : path, 'seed_mode' : True})
            if meta['debug']:
                console.print(f"[cyan]Path: {path}")
        else:
            console.print("[bold red]Unable to connect to deluge")




    def add_fast_resume(self, metainfo, datapath, torrent):
        """ Add fast resume data to a metafile dict.
        """
        # Get list of files
        files = metainfo["info"].get("files", None)
        single = files is None
        if single:
            if os.path.isdir(datapath):
                datapath = os.path.join(datapath, metainfo["info"]["name"])
            files = [Bunch(
                path=[os.path.abspath(datapath)],
                length=metainfo["info"]["length"],
            )]

        # Prepare resume data
        resume = metainfo.setdefault("libtorrent_resume", {})
        resume["bitfield"] = len(metainfo["info"]["pieces"]) // 20
        resume["files"] = []
        piece_length = metainfo["info"]["piece length"]
        offset = 0

        for fileinfo in files:
            # Get the path into the filesystem
            filepath = os.sep.join(fileinfo["path"])
            if not single:
                filepath = os.path.join(datapath, filepath.strip(os.sep))

            # Check file size
            if os.path.getsize(filepath) != fileinfo["length"]:
                raise OSError(errno.EINVAL, "File size mismatch for %r [is %d, expected %d]" % (
                    filepath, os.path.getsize(filepath), fileinfo["length"],
                ))

            # Add resume data for this file
            resume["files"].append(dict(
                priority=1,
                mtime=int(os.path.getmtime(filepath)),
                completed=(offset+fileinfo["length"]+piece_length-1) // piece_length
                        - offset // piece_length,
            ))
            offset += fileinfo["length"]

        return metainfo


    async def remote_path_map(self, meta):
        if meta.get('client', None) == None:
            torrent_client = self.config['DEFAULT']['default_torrent_client']
        else:
            torrent_client = meta['client']
        local_path = list_local_path = self.config['TORRENT_CLIENTS'][torrent_client].get('local_path','/LocalPath')
        remote_path = list_remote_path = self.config['TORRENT_CLIENTS'][torrent_client].get('remote_path', '/RemotePath')
        if isinstance(local_path, list):
            for i in range(len(local_path)):
                if os.path.normpath(local_path[i]).lower() in meta['path'].lower():
                    list_local_path = local_path[i]
                    list_remote_path = remote_path[i]
            
        local_path = os.path.normpath(list_local_path)
        remote_path = os.path.normpath(list_remote_path)
        if local_path.endswith(os.sep):
            remote_path = remote_path + os.sep

        return local_path, remote_path