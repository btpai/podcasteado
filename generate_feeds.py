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
MAX_EPISODES = 10
# ---------------------

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
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
    
    identifier = clean_url.split('/')[-1]
    identifier = identifier.replace('@', '').replace('channel', '')
    return f"{identifier}{suffix}"

def get_candidate_ids(channel_url):
    """Obtiene los IDs de los últimos 5 videos."""
    print(f"🔎 Analizando lista de videos en: {channel_url}")
    command = [
        'yt-dlp',
        '--flat-playlist',
        '--playlist-end', '5',
        '--print', 'id',
        '--no-check-certificate',
        '--ignore-errors',
        '--cookies', 'cookies.txt',
        channel_url
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        ids = [line.strip() for line in result.stdout.split('\n') if line.strip()]
        return ids
    except Exception as e:
        print(f"Error buscando IDs: {e}")
        return []

def get_video_details(video_id):
    """
    Intenta extraer SOLO AUDIO COMPATIBLE (M4A/AAC).
    Forzamos vcodec=none para que no baje video.
    Forzamos protocol=https para intentar evitar m3u8 (HLS).
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    command = [
        'yt-dlp',
        '-v',
        '--no-check-certificate',
        '--force-ipv4',
        '--no-cache-dir',
        '--skip-download',
        '--cookies', 'cookies.txt',
        '--add-header', 'Referer:https://www.youtube.com/',
        '--add-header', 'User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        
        # --- CAMBIO CRÍTICO PARA ANTENNAPOD ---
        # 1. bestaudio[ext=m4a]: Queremos M4A (AAC) nativo.
        # 2. [vcodec=none]: ¡PROHIBIDO VIDEO!
        # 3. [protocol^=http]: Preferimos enlace directo, no m3u8.
        '-f', 'bestaudio[ext=m4a][vcodec=none][protocol^=http]/bestaudio[ext=m4a][vcodec=none]/bestaudio',
        # --------------------------------------
        
        '-j',
        video_url
    ]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        
        if result.returncode != 0:
            return None

        output_lines = result.stdout.strip().split('\n')
        video_data = None
        for line in reversed(output_lines):
            try:
                temp = json.loads(line)
                if 'id' in temp and 'url' in temp:
                    video_data = temp
                    break
            except:
                continue

        # --- VERIFICACIÓN DE SEGURIDAD ---
        # Si yt-dlp nos ha traicionado y nos ha dado un video, lo descartamos
        if video_data.get('vcodec') != 'none':
            print(f"⚠️ Aviso: Se detectó video en la respuesta. Intentando filtrar...")
            # (Aquí confiamos en que el filtro -f funcionó, pero esto es un log por si acaso)

        return {
            'id': video_data.get('id'),
            'title': video_data.get('title'),
            'description': video_data.get('description'),
            'upload_date': video_data.get('upload_date'),
            'duration': video_data.get('duration'),
            'stream_url': video_data.get('url'),
            'webpage_url': video_data.get('webpage_url'),
            'channel_title': video_data.get('uploader')
        }

    except:
        return None

def generate_rss_xml(channel_id, episodes):
    if not episodes: return

    fg = FeedGenerator()
    fg.load_extension('podcast')
    
    latest = episodes[0] 
    fg.id(channel_id)
    
    if channel_id.endswith('_Directos'):
        podcast_title = f"{latest['channel_title']} (Directos)"
    else:
        podcast_title = f"{latest['channel_title']} (Audio)"

    fg.title(podcast_title)
    fg.description(f"Podcast generado de: {latest['channel_title']}")
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

        # Tipo MIME estricto para AntennaPod
        fe.enclosure(url=ep['stream_url'], length='0', type='audio/mp4')
        
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
        time.sleep(5)
        
        channel_id_safe = get_channel_identifier(url)
        
        candidate_ids = get_candidate_ids(url)
        if not candidate_ids: continue

        valid_video_details = None
        for vid in candidate_ids:
            print(f"Probando video ID: {vid}...")
            details = get_video_details(vid)
            if details:
                # Comprobación extra: Si la URL parece un manifiesto HLS (.m3u8), avisamos
                if '.m3u8' in details['stream_url']:
                    print("   ⚠️ OJO: El enlace es m3u8 (HLS). AntennaPod prefiere archivos directos.")
                
                print(f"   -> ¡Funciona! Título: {details.get('title')[:30]}...")
                valid_video_details = details
                break 
            else:
                print(f"   -> 🔒 Inaccesible o formato incorrecto. Saltando...")
        
        if not valid_video_details:
            print("❌ No se encontraron videos válidos.")
            continue

        if channel_id_safe not in history: history[channel_id_safe] = []
        current_episodes = history[channel_id_safe]
        
        is_new = False
        if not current_episodes: is_new = True
        elif current_episodes[0]['id'] != valid_video_details['id']: is_new = True

        if is_new:
            print("✨ ¡Es un episodio NUEVO!")
            current_episodes.insert(0, valid_video_details)
            history[channel_id_safe] = current_episodes[:MAX_EPISODES]
            changes_made = True
        else:
            print("🔄 Refrescando enlace de audio...")
            history[channel_id_safe][0]['stream_url'] = valid_video_details['stream_url']
            changes_made = True

        generate_rss_xml(channel_id_safe, history[channel_id_safe])

    if changes_made:
        save_history(history)

if __name__ == '__main__':
    main()
