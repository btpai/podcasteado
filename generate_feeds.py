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
MAX_EPISODES = 15 # Aumentamos un poco para tener margen

# Instancia Invidious para la reproducción (Tu móvil se conectará aquí).
# Usamos inv.tux.pizza que suele ser robusta, o puedes volver a yewtu.be
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
    NO conecta con APIs externas.
    """
    print(f"🔎 Leyendo índice del canal: {channel_url}")
    command = [
        'yt-dlp',
        '--dump-single-json',  # Devuelve todo en un solo JSON gigante
        '--flat-playlist',     # CRUCIAL: No analiza los videos, solo lista
        '--playlist-end', '10', # Leemos los últimos 10
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
        
        # En modo flat, 'entries' tiene la lista de videos
        if 'entries' not in data:
            return []
            
        videos_found = []
        
        for entry in data['entries']:
            # En modo flat, entry tiene 'id', 'title', 'url' pero no 'description' completa
            vid_id = entry.get('id')
            title = entry.get('title')
            
            # Filtramos videos privados o borrados que a veces salen sin título
            if not vid_id or not title or title == '[Private video]':
                continue

            # --- CONSTRUCCIÓN CIEGA DEL ENLACE ---
            # No comprobamos si funciona. Asumimos que sí.
            # AntennaPod hará el trabajo duro.
            proxy_url = f"{INVIDIOUS_DOMAIN}/latest_version?id={vid_id}&itag=18"
            
            videos_found.append({
                'id': vid_id,
                'title': title,
                'description': "Descripción no disponible en modo rápido.", # yt-dlp flat no da descripción
                'upload_date': entry.get('upload_date'), # A veces viene, a veces no
                'duration': entry.get('duration'), # A veces viene
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
    
    # Datos del canal (usamos el del video más nuevo)
    latest = episodes[0]
    
    suffix = " (Directos)" if channel_id.endswith('_Directos') else ""
    fg.title(f"{latest['channel_title']}{suffix}")
    fg.description(f"Feed generado para: {latest['channel_title']}")
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
                # yt-dlp flat suele devolver string 'YYYYMMDD' si está disponible
                date_obj = datetime.strptime(ep['upload_date'], '%Y%m%d')
                fe.pubDate(date_obj.replace(tzinfo=datetime.now().astimezone().tzinfo))
            else:
                # Si no hay fecha, usamos la hora actual para que no falle, 
                # o no ponemos nada. Poner "ahora" asegura que aparezca arriba.
                # fe.pubDate(datetime.now().replace(tzinfo=datetime.now().astimezone().tzinfo))
                pass
        except: pass

        # Enlace VIDEO MP4 permanente vía Invidious
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
        
        # 1. Obtenemos lista de videos (Modo Flat)
        latest_videos = get_latest_videos_flat(url)
        
        if not latest_videos:
            print("❌ No se encontraron videos.")
            continue

        print(f"   -> Encontrados {len(latest_videos)} videos en el índice.")

        # 2. Actualizar Historial
        if channel_id_safe not in history: history[channel_id_safe] = []
        current_episodes = history[channel_id_safe]
        
        # Comparamos el ID del más nuevo
        if not current_episodes or current_episodes[0]['id'] != latest_videos[0]['id']:
            print(f"✨ Nuevo episodio: {latest_videos[0]['title']}")
            # Reemplazamos la lista con los nuevos datos frescos del índice
            # Esto corrige enlaces o títulos si cambiaron, y añade los nuevos
            history[channel_id_safe] = latest_videos
            changes_made = True
        else:
            print("🔄 Sin novedades (ID coincide).")

        generate_rss_xml(channel_id_safe, history[channel_id_safe])

    if changes_made:
        save_history(history)

if __name__ == '__main__':
    main()
