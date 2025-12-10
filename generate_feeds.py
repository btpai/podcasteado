import subprocess
import json
import os
import time
import urllib.request
from feedgen.feed import FeedGenerator
from datetime import datetime

# --- CONFIGURACIÓN ---
OUTPUT_DIR = 'feeds'
CHANNELS_FILE = 'channels.txt'
HISTORY_FILE = 'history.json'
MAX_EPISODES = 10

# Usamos la API de Invidious para obtener títulos sin tocar YouTube
INVIDIOUS_INSTANCE = "https://yewtu.be"
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

def get_candidate_ids(channel_url):
    """Obtiene los IDs usando yt-dlp en modo 'flat' (menos bloqueos)."""
    print(f"🔎 Analizando canal: {channel_url}")
    command = [
        'yt-dlp',
        '--flat-playlist',
        '--playlist-end', '5',
        '--print', 'id',
        '--no-check-certificate',
        '--ignore-errors',
        channel_url
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        return [line.strip() for line in result.stdout.split('\n') if line.strip()]
    except:
        return []

def get_video_metadata_via_api(video_id):
    """
    Obtiene los detalles consultando la API de Invidious.
    ESTO EVITA EL BLOQUEO DE YOUTUBE A GITHUB.
    """
    api_url = f"{INVIDIOUS_INSTANCE}/api/v1/videos/{video_id}"
    
    try:
        # Hacemos una petición HTTP a Invidious
        req = urllib.request.Request(
            api_url, 
            headers={'User-Agent': 'Mozilla/5.0'} # Cortesía para no parecer un bot malo
        )
        
        with urllib.request.urlopen(req) as response:
            if response.status != 200:
                print(f"   ⚠️ API Invidious error {response.status}")
                return None
            
            data = json.loads(response.read().decode())
            
            # Si Invidious dice que hay error, salimos
            if 'error' in data:
                return None

            # Construimos el enlace permanente de video (MP4 360p - itag 18)
            # Este enlace funciona siempre, no caduca y no requiere IP específica.
            proxy_url = f"{INVIDIOUS_INSTANCE}/latest_version?id={video_id}&itag=18"

            return {
                'id': video_id,
                'title': data.get('title'),
                'description': data.get('description') or "Sin descripción",
                'upload_date': str(data.get('published')), # Timestamp o string
                'duration': data.get('lengthSeconds'),
                'stream_url': proxy_url,
                'webpage_url': f"https://www.youtube.com/watch?v={video_id}",
                'channel_title': data.get('author')
            }
            
    except Exception as e:
        print(f"   ❌ Error conectando con Invidious API: {e}")
        return None

def generate_rss_xml(channel_id, episodes):
    if not episodes: return
    fg = FeedGenerator()
    fg.load_extension('podcast')
    latest = episodes[0] 
    fg.id(channel_id)
    
    suffix = " (Directos)" if channel_id.endswith('_Directos') else ""
    # Aseguramos que haya un título de canal
    c_title = latest.get('channel_title') or channel_id
    
    fg.title(f"{c_title}{suffix}")
    fg.description(f"Feed Invidious: {c_title}")
    fg.link(href=latest['webpage_url'], rel='alternate')
    fg.language('es')

    for ep in episodes:
        fe = fg.add_entry()
        fe.id(ep['id'])
        fe.title(ep['title'])
        fe.link(href=ep['webpage_url'])
        fe.description(ep['description'])
        
        # Invidious devuelve la fecha como timestamp (int) a veces
        try:
            if ep.get('upload_date'):
                # Si es un número (timestamp UNIX)
                if isinstance(ep['upload_date'], int):
                    date_obj = datetime.fromtimestamp(ep['upload_date'])
                else:
                    # Intento genérico de parseo si viene como string
                    date_obj = datetime.now() 
                
                fe.pubDate(date_obj.replace(tzinfo=datetime.now().astimezone().tzinfo))
        except: pass

        # Enlace de Video MP4 (AntennaPod lo reproducirá con video)
        fe.enclosure(url=ep['stream_url'], length='0', type='video/mp4')
        
        if ep.get('duration'): fe.podcast.itunes_duration(ep['duration'])

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
        
        # 1. Obtener IDs (yt-dlp flat playlist suele funcionar bien)
        candidate_ids = get_candidate_ids(url)
        if not candidate_ids: continue

        # 2. Obtener datos via API
        valid_video = None
        for vid in candidate_ids:
            print(f"Consultando API para ID: {vid}...")
            details = get_video_metadata_via_api(vid)
            
            if details and details.get('title'):
                print(f"   -> OK: {details['title'][:30]}...")
                valid_video = details
                break
            else:
                print("   -> Fallo en API. Probando siguiente...")
                time.sleep(1) # Pausa para no saturar la API

        if not valid_video: 
            print("❌ No se pudo obtener información de ningún video.")
            continue

        # 3. Guardar
        if channel_id_safe not in history: history[channel_id_safe] = []
        current_episodes = history[channel_id_safe]
        
        # Comparamos IDs
        is_new = not current_episodes or current_episodes[0]['id'] != valid_video['id']

        if is_new:
            print("✨ Nuevo episodio añadido.")
            current_episodes.insert(0, valid_video)
            history[channel_id_safe] = current_episodes[:MAX_EPISODES]
            changes_made = True
        else:
            print("🔄 Episodio ya existente.")

        generate_rss_xml(channel_id_safe, history[channel_id_safe])

    if changes_made:
        save_history(history)

if __name__ == '__main__':
    main()
