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

# Instancia de Invidious a usar (Proxy). 
# yewtu.be es muy fiable. Si falla, prueba: inv.tux.pizza
INVIDIOUS_DOMAIN = "https://yewtu.be" 
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
    """Usa yt-dlp SOLO para obtener IDs (sin cookies)."""
    print(f"🔎 Analizando canal: {channel_url}")
    command = [
        'yt-dlp',
        '--flat-playlist',     # No descarga nada, solo lee la lista
        '--playlist-end', '5', # Mira los últimos 5 videos
        '--print', 'id',       # Solo devuelve los IDs
        '--no-check-certificate',
        '--ignore-errors',
        channel_url
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        return [line.strip() for line in result.stdout.split('\n') if line.strip()]
    except:
        return []

def get_video_metadata(video_id):
    """
    Obtiene título y descripción. 
    NO intenta sacar el enlace de video de YouTube (eso fallaba).
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    command = [
        'yt-dlp',
        '--skip-download',
        '--no-check-certificate',
        '--ignore-errors',
        '--extractor-args', 'youtube:player_client=android', # Truco anti-bot ligero
        '-j', # Salida JSON
        video_url
    ]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0: return None
        
        # Parseo seguro del JSON
        output_lines = result.stdout.strip().split('\n')
        video_data = None
        for line in reversed(output_lines):
            try:
                temp = json.loads(line)
                if 'id' in temp:
                    video_data = temp
                    break
            except: continue
            
        if not video_data: return None

        # --- AQUÍ ESTÁ LA MAGIA ---
        # En lugar de usar la URL de YouTube que caduca y pide cookies,
        # construimos una URL permanente a través de Invidious.
        # itag=18 es MP4 360p (Video+Audio). Compatible con todo.
        proxy_url = f"{INVIDIOUS_DOMAIN}/latest_version?id={video_id}&itag=18"

        return {
            'id': video_data.get('id'),
            'title': video_data.get('title'),
            'description': video_data.get('description') or "Sin descripción",
            'upload_date': video_data.get('upload_date'),
            'duration': video_data.get('duration'),
            'stream_url': proxy_url, # <--- Usamos el enlace Proxy
            'webpage_url': f"https://www.youtube.com/watch?v={video_id}",
            'channel_title': video_data.get('uploader') or "Canal Desconocido"
        }
    except:
        return None

def generate_rss_xml(channel_id, episodes):
    if not episodes: return
    fg = FeedGenerator()
    fg.load_extension('podcast')
    latest = episodes[0] 
    fg.id(channel_id)
    
    suffix = " (Directos)" if channel_id.endswith('_Directos') else ""
    fg.title(f"{latest['channel_title']}{suffix}")
    fg.description(f"Feed generado vía Invidious para: {latest['channel_title']}")
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

        # Le decimos a AntennaPod que es Video MP4
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
        time.sleep(3) # Pequeña pausa
        channel_id_safe = get_channel_identifier(url)
        
        # 1. Obtenemos IDs
        candidate_ids = get_candidate_ids(url)
        if not candidate_ids: continue

        # 2. Buscamos el primer video válido (Metadata + Invidious)
        valid_video = None
        for vid in candidate_ids:
            print(f"Procesando ID: {vid}...")
            # Aquí ya no fallará por cookies porque solo pedimos texto (metadata)
            details = get_video_metadata(vid)
            
            # Si el video es de miembros, yt-dlp suele fallar al sacar metadata
            # o devolver título null. Si tenemos datos, asumimos que es público.
            if details and details.get('title'):
                print(f"   -> OK: {details['title'][:30]}...")
                valid_video = details
                break
            else:
                print("   -> Inaccesible/Miembros. Saltando.")

        if not valid_video: continue

        # 3. Guardar en historial
        if channel_id_safe not in history: history[channel_id_safe] = []
        current_episodes = history[channel_id_safe]
        
        is_new = not current_episodes or current_episodes[0]['id'] != valid_video['id']

        if is_new:
            print("✨ Nuevo episodio añadido.")
            current_episodes.insert(0, valid_video)
            history[channel_id_safe] = current_episodes[:MAX_EPISODES]
            changes_made = True
        else:
            # Aunque no sea nuevo, regeneramos el XML por si borraste el archivo
            print("🔄 Episodio existente.")
            # IMPORTANTE: No hace falta refrescar el enlace porque el enlace de Invidious
            # es PERMANENTE. Nunca caduca.

        generate_rss_xml(channel_id_safe, history[channel_id_safe])

    if changes_made:
        save_history(history)

if __name__ == '__main__':
    main()
