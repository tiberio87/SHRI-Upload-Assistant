#!/usr/bin/env python3
"""
Generate realistic meta objects from media files using Upload Assistant's code.
Output saved to generated_meta.json for use in test suite.

Usage: python meta_generator.py /path/to/video.mkv
"""

import sys
import json
import asyncio
import os

from data.config import config
from src.prep import Prep
from src.args import Args
from src.get_name import get_name
from src.languages import process_desc_language


async def generate_meta(filepath):
    """
    Generate meta using Upload Assistant's actual code path.
    Mirrors upload.py workflow to ensure authentic metadata structure.
    """
    if not os.path.isfile(filepath):
        raise ValueError(f"Path must be a video file, not a directory: {filepath}")
    
    parser = Args(config)
    
    meta = {}
    meta, _, _ = parser.parse(('--path', filepath), meta)
    
    # Set required fields (mirrors upload.py)
    if meta.get('imghost') is None:
        meta['imghost'] = config['DEFAULT'].get('img_host_1', 'imgbb')
    
    base_dir = os.path.abspath(os.path.dirname(__file__))
    meta['base_dir'] = base_dir
    
    prep = Prep(screens=meta.get('screens', 0), img_host=meta['imghost'], config=config)
    print("Gathering metadata...")
    meta = await prep.gather_prep(meta=meta, mode='cli')
    
    print("Processing audio languages...")
    await process_desc_language(meta, desc=None, tracker='SHRI')
    
    print("Generating release name...")
    meta['name_notag'], meta['name'], meta['clean_name'], meta['potential_missing'] = await get_name(meta)
    
    return meta


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python meta_generator.py /path/to/video.mkv")
        sys.exit(1)
    
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    
    try:
        meta = asyncio.run(generate_meta(filepath))
        
        display_fields = [
            'name', 'type', 'resolution', 'video_codec', 'source', 
            'audio', 'year', 'title', 'tag', 'audio_languages', 
            'dual_audio', 'is_disc', 'language_checked', 'filelist', 'path'
        ]
        
        display_meta = {k: meta.get(k) for k in display_fields if k in meta}
        
        print("\n" + "="*60)
        print("GENERATED META (key fields):")
        print("="*60)
        print(json.dumps(display_meta, indent=2, default=str))
        
        # Generate output filename from source
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        # Sanitize filename for filesystem
        safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in base_name)
        output_file = f'generated_meta_{safe_name}.json'

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, default=str)

        print(f"\nFull meta saved to: {output_file}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)