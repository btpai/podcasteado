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

# Instancia Invidious
# Si inv.tux.pizza falla, prueba: https://inv.nadeko.net o https://yewtu.be
INVIDIOUS_DOMAIN = "https://inv.tux.pizza"
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
    Obtiene Título e ID directamente del índice del canal.
    NO hace peticiones individuales a los videos.
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
        # Ejecutamos yt-dlp
        result = subprocess.run(command, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"⚠️ Error leyendo índice. Code: {result.returncode}")
            return []

        data = json.loads(result.stdout)
        
        if 'entries' not in data:
            return []
            
        videos_found = []
        
        for entry in data['entries']:
            vid_id = entry.get('id')
            title = entry.get('title')
            
            if not vid_id or not title or title == '[Private video]':
                continue

            # --- MODO VLC / M3U8 ---
            # Construimos el enlace al manifiesto HLS.
            # ?subs=0 desactiva subtítulos por defecto para evitar problemas en algunos reproductores.
            proxy_url = f"{INVIDIOUS_DOMAIN}/api/manifest/hls_variant/{vid_id}.m3u8?subs=0"
            
            videos_found.append({
                'id': vid_id,
                'title': title,
                'description': "Streaming HLS vía Invidious.",
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
    fg.description(f"Feed VLC (M3U8): {latest['channel_title']}")
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

        # --- TIPO MIME CORRECTO PARA M3U8 ---
        # Usamos application/x-mpegURL para que VLC lo reconozca como lista de streaming
        fe.enclosure(url=ep['stream_url'], length='0', type='video/mp4')
        
        # Corrección de duración (con protección anti-errores)
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

        print(f"   -> Encontrados {len(latest_videos)} videos en el índice.")

        if channel_id_safe not in history: history[channel_id_safe] = []
        current_episodes = history[channel_id_safe]
        
        # Comprobamos si hay novedad o simplemente forzamos actualización de URLs
        if not current_episodes or current_episodes[0]['id'] != latest_videos[0]['id']:
            print(f"✨ Nuevo episodio detectado: {latest_videos[0]['title']}")
            history[channel_id_safe] = latest_videos
            changes_made = True
        else:
            print("🔄 Refrescando URLs M3U8...")
            history[channel_id_safe] = latest_videos
            changes_made = True

        generate_rss_xml(channel_id_safe, history[channel_id_safe])

    if changes_made:
        save_history(history)

if __name__ == '__main__':
    main()
