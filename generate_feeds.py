import subprocess
import json
import os
import time
from feedgen.feed import FeedGenerator
from datetime import datetime

# --- CONFIGURACIÓN ---
OUTPUT_DIR = 'feeds'
CHANNELS_FILE = 'channels.txt'
HISTORY_FILE = 'history.json'
MAX_EPISODES = 15 

# Usamos el Proxy de Piped (Kavin Rocks). Es muy rápido y estable.
# Si falla, otras opciones: 
# https://pipedproxy.adminforge.de
# https://pp.drg.li
PIPED_PROXY = "https://pipedproxy.kavin.rocks"
PIPED_API_HOST = "pipedapi.kavin.rocks"
# ---------------------

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=4)

def get_channel_identifier(url):
    clean_url = url.strip().rstrip('/')
    suffix = ""
    if clean_url.endswith('/streams'):
        clean_url = clean_url[:-8]
        suffix = "_Directos"
    elif clean_url.endswith('/videos'):
        clean_url = clean_url[:-7]
    identifier = clean_url.split('/')[-1].replace('@', '').replace('channel', '')
    return f"{identifier}{suffix}"

def get_latest_videos_flat(channel_url):
    """
    Modo Flat Dump.
    Usa yt-dlp solo para leer el índice (seguro).
    Genera enlaces de PIPED PROXY.
    """
    print(f"🔎 Leyendo índice del canal: {channel_url}")
    command = [
        'yt-dlp',
        '--dump-single-json', 
        '--flat-playlist',     
        '--playlist-end', '10', 
        '--no-check-certificate',
        '--ignore-errors',
        channel_url
    ]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0: return []

        data = json.loads(result.stdout)
        if 'entries' not in data: return []
            
        videos_found = []
        
        for entry in data['entries']:
            vid_id = entry.get('id')
            title = entry.get('title')
            
            if not vid_id or not title or title == '[Private video]':
                continue

            # --- MODO PIPED PROXY (M3U8) ---
            # Construimos el enlace al manifiesto HLS de Piped.
            # Esto es MUCHO más estable que Invidious para VLC.
            proxy_url = f"{PIPED_PROXY}/hls/manifest/{vid_id}.m3u8?host={PIPED_API_HOST}"
            
            videos_found.append({
                'id': vid_id,
                'title': title,
                'description': "Streaming HLS vía Piped.",
                'upload_date': entry.get('upload_date'),
                'duration': entry.get('duration'),
                'stream_url': proxy_url,
                'webpage_url': f"https://www.youtube.com/watch?v={vid_id}",
                'channel_title': data.get('uploader') or data.get('title') or "Canal"
            })
            
        return videos_found

    except Exception as e:
        print(f"❌ Error crítico procesando canal: {e}")
        return []

def generate_rss_xml(channel_id, episodes):
    if not episodes: return
    fg = FeedGenerator()
    fg.load_extension('podcast')
    
    latest = episodes[0]
    
    suffix = " (Directos)" if channel_id.endswith('_Directos') else ""
    fg.title(f"{latest['channel_title']}{suffix}")
    fg.description(f"Feed VLC (Piped): {latest['channel_title']}")
    fg.link(href=latest['webpage_url'], rel='alternate')
    fg.language('es')

    for ep in episodes:
        fe = fg.add_entry()
        fe.id(ep['id'])
        fe.title(ep['title'])
        fe.link(href=ep['webpage_url'])
        fe.description(ep['description'])
        
        try:
            if ep.get('upload_date'):
                date_obj = datetime.strptime(ep['upload_date'], '%Y%m%d')
                fe.pubDate(date_obj.replace(tzinfo=datetime.now().astimezone().tzinfo))
        except: pass

        # Tipo MIME para VLC (M3U8)
        fe.enclosure(url=ep['stream_url'], length='0', type='application/x-mpegURL')
        
        # Corrección de duración (protección anti-fallos)
        duration_raw = ep.get('duration')
        if duration_raw:
            try:
                seconds = int(float(duration_raw))
                fe.podcast.itunes_duration(seconds)
            except (ValueError, TypeError):
                pass 

    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    filename = f'{channel_id}.xml'
    fg.rss_file(os.path.join(OUTPUT_DIR, filename), pretty=True)
    print(f"✅ Feed generado: {filename}")

def main():
    if not os.path.exists(CHANNELS_FILE):
        print(f"Falta {CHANNELS_FILE}")
        return

    history = load_history()
    with open(CHANNELS_FILE, 'r') as f:
        channels = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    changes_made = False

    for url in channels:
        print(f"\n--- Procesando Canal ---")
        time.sleep(2)
        channel_id_safe = get_channel_identifier(url)
        
        latest_videos = get_latest_videos_flat(url)
        
        if not latest_videos:
            print("❌ No se encontraron videos.")
            continue

        print(f"   -> Encontrados {len(latest_videos)} videos.")

        if channel_id_safe not in history: history[channel_id_safe] = []
        current_episodes = history[channel_id_safe]
        
        if not current_episodes or current_episodes[0]['id'] != latest_videos[0]['id']:
            print(f"✨ Nuevo episodio: {latest_videos[0]['title']}")
            history[channel_id_safe] = latest_videos
            changes_made = True
        else:
            print("🔄 Refrescando URLs Piped...")
            history[channel_id_safe] = latest_videos
            changes_made = True

        generate_rss_xml(channel_id_safe, history[channel_id_safe])

    if changes_made:
        save_history(history)

if __name__ == '__main__':
    main()
