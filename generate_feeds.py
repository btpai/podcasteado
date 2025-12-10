import subprocess
import json
import os
from feedgen.feed import FeedGenerator
from datetime import datetime

# --- CONFIGURACIÓN ---
OUTPUT_DIR = 'feeds'
CHANNELS_FILE = 'channels.txt'
HISTORY_FILE = 'history.json'
MAX_EPISODES = 10  # Cuántos episodios mantener en el feed
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
    # Intenta limpiar la URL para usarla como nombre de archivo
    parts = url.split('/')
    if 'channel' in parts:
        return parts[parts.index('channel') + 1]
    return parts[-1].replace('@', '').replace('videos', '')

def get_latest_video_id(channel_url):
    """PASO 1: Obtener solo el ID del video más reciente (Rápido y seguro)."""
    print(f"🔎 Buscando ID del último video en: {channel_url}")
    command = [
        'yt-dlp',
        '--flat-playlist',          # NO procesar el video, solo listar
        '--playlist-end', '1',      # Solo el primero
        '--print', 'id',            # Solo imprime el ID
        '--no-check-certificate',
        '--ignore-errors',
        channel_url
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        video_id = result.stdout.strip()
        if video_id and len(video_id) < 15: # Validación básica de ID
            print(f"   📍 ID encontrado: {video_id}")
            return video_id
    except Exception as e:
        print(f"Error buscando ID: {e}")
    
    print("❌ No se pudo obtener el ID del video.")
    return None

def get_video_details(video_id):
    """PASO 2: Obtener audio usando cliente Android para evitar bloqueos."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"🎵 Extrayendo audio de: {video_url}")
    
    command = [
        'yt-dlp',
        '-v',
        '--no-check-certificate',
        '--force-ipv4',
        '--no-cache-dir',
        '--skip-download',
        '--cookies', 'cookies.txt',       
        '-f', 'bestaudio[ext=m4a]/bestaudio/best',
        '-j',
        video_url
    ]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        
        # He descomentado el error para que si falla, veamos EXACTAMENTE qué dice YouTube
        if result.returncode != 0:
            print(f"⚠️ Error extrayendo detalles. Code: {result.returncode}")
            print(f"ERROR REAL: {result.stderr[-500:]}") # Imprimimos los últimos 500 caracteres

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

        if not video_data:
            return None

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

    except Exception as e:
        print(f"Error obteniendo detalles: {e}")
        return None

def generate_rss_xml(channel_id, episodes):
    if not episodes: return

    fg = FeedGenerator()
    fg.load_extension('podcast')
    
    latest = episodes[0] 
    fg.id(channel_id)
    fg.title(f"{latest['channel_title']} (Audio)")
    fg.description(f"Podcast de: {latest['channel_title']}")
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
                fe.pubdate(date_obj.replace(tzinfo=datetime.now().astimezone().tzinfo))
        except: pass

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
        print(f"--- Procesando Canal ---")
        channel_id_safe = get_channel_identifier(url)
        
        # 1. CONSEGUIR ID
        video_id = get_latest_video_id(url)
        if not video_id: continue

        # 2. VERIFICAR SI ES NUEVO
        if channel_id_safe not in history: history[channel_id_safe] = []
        current_episodes = history[channel_id_safe]
        
        is_new = False
        if not current_episodes: is_new = True
        elif current_episodes[0]['id'] != video_id: is_new = True

        # 3. EXTRAER DETALLES (Solo si es nuevo o para refrescar el link)
        if is_new:
            print("¡Video Nuevo! Descargando info...")
            details = get_video_details(video_id)
            if details:
                current_episodes.insert(0, details)
                history[channel_id_safe] = current_episodes[:MAX_EPISODES]
                changes_made = True
        else:
            print("Video repetido. Refrescando enlace...")
            # Opcional: Volver a pedir detalles para refrescar el link caducado
            details = get_video_details(video_id)
            if details:
                history[channel_id_safe][0]['stream_url'] = details['stream_url']
                changes_made = True

        generate_rss_xml(channel_id_safe, history[channel_id_safe])

    if changes_made:
        save_history(history)

if __name__ == '__main__':
    main()
