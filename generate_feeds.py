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
def get_latest_video_info(channel_url):
    """
    Versión robusta con argumentos 'safe-mode' para servidores.
    """
    print(f"🔍 Procesando: {channel_url}")
    
    command = [
        'yt-dlp',
        # --- BLOQUE DE SEGURIDAD Y RED ---
        '-v',                       # Verbose: Para ver qué pasa si falla
        '--ignore-errors',          # Si hay un error, intenta continuar
        '--no-check-certificate',   # Evita errores de SSL en servidores antiguos
        '--force-ipv4',             # Crucial: GitHub Actions a veces falla con IPv6
        '--no-cache-dir',           # No usar caché para evitar datos corruptos
        
        # --- BLOQUE DE EXTRACCIÓN ---
        '--playlist-end', '1',      # Solo el primer video
        '--skip-download',          # NO descargar el archivo
        '-f', 'bestaudio/best',     # El mejor audio disponible
        '-j',                       # Salida en formato JSON
        
        # --- LA URL ---
        channel_url
    ]
    
    try:
        # Ejecutamos el comando
        result = subprocess.run(command, capture_output=True, text=True)
        
        # Si falló, imprimimos el error pero no rompemos el script inmediatamente
        if result.returncode != 0:
            print(f"⚠️ Alerta: yt-dlp devolvió código {result.returncode}")
            print(f"   STDERR: {result.stderr[:500]}...") # Primeros 500 caracteres del error
            # A veces devuelve error pero imprime el JSON igual, intentamos seguir...

        # Procesar el JSON
        # yt-dlp puede imprimir varias líneas de logs antes del JSON.
        # Buscamos la última línea que parezca un JSON válido.
        output_lines = result.stdout.strip().split('\n')
        
        video_data = None
        for line in reversed(output_lines):
            try:
                temp_data = json.loads(line)
                # Verificamos que sea un video y tenga URL
                if 'id' in temp_data and 'url' in temp_data:
                    video_data = temp_data
                    break
            except json.JSONDecodeError:
                continue

        if not video_data:
            print(f"❌ No se encontró JSON válido para {channel_url}")
            return None
            
        print(f"✅ Éxito: {video_data.get('title')}")
        
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
        print(f"❌ Error crítico en script Python: {e}")
        return None
        
def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=4)

def get_channel_identifier(url):
    return url.split('/')[-1].replace('@', '').replace('user/', '').replace('channel/', '')

def get_latest_video_info(channel_url):
    """Obtiene info del último video usando yt-dlp."""
    try:
        # Extraemos ID, Titulo, URL directa, etc.
        command = [
            'yt-dlp', 
            '--playlist-end', '1', 
            '--skip-download', 
            '-f', 'bestaudio[ext=m4a]/bestaudio/best', # Priorizamos m4a para podcasts
            '-j', 
            channel_url
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        video_data = json.loads(result.stdout.strip().split('\n')[-1])
        
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
        print(f"Error procesando {channel_url}: {e}")
        return None

def generate_rss_xml(channel_id, episodes):
    """Genera el XML del podcast con la lista de episodios."""
    if not episodes:
        return

    fg = FeedGenerator()
    fg.load_extension('podcast')
    
    # Usamos los datos del último video para llenar la info del canal
    latest = episodes[0] 
    fg.id(channel_id)
    fg.title(f"{latest['channel_title']} (Audio)")
    fg.description(f"Podcast generado automáticamente de: {latest['channel_title']}")
    fg.link(href=latest['webpage_url'], rel='alternate')
    fg.language('es')

    # Añadir episodios al feed
    for ep in episodes:
        fe = fg.add_entry()
        fe.id(ep['id'])
        fe.title(ep['title'])
        fe.link(href=ep['webpage_url'])
        fe.description(ep['description'])
        
        # Formatear fecha para RSS (yyyymmdd -> datetime)
        try:
            date_obj = datetime.strptime(ep['upload_date'], '%Y%m%d')
            fe.pubdate(date_obj.replace(tzinfo=datetime.now().astimezone().tzinfo))
        except:
            pass

        # Enlace directo al audio (M3U/Link directo)
        fe.enclosure(url=ep['stream_url'], length='0', type='audio/mp4')
        
        if ep.get('duration'):
            fe.podcast.itunes_duration(ep['duration'])

    # Guardar archivo
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    filename = f'{channel_id}.xml'
    fg.rss_file(os.path.join(OUTPUT_DIR, filename), pretty=True)
    print(f"Feed actualizado: {filename}")

def main():
    if not os.path.exists(CHANNELS_FILE):
        print(f"No se encontró {CHANNELS_FILE}")
        return

    history = load_history()
    
    with open(CHANNELS_FILE, 'r') as f:
        channels = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    changes_made = False

    for url in channels:
        print(f"Revisando canal: {url}...")
        channel_id = get_channel_identifier(url)
        video_info = get_latest_video_info(url)
        
        if not video_info:
            continue

        # Inicializar historial para este canal si no existe
        if channel_id not in history:
            history[channel_id] = []

        current_episodes = history[channel_id]
        
        # --- DETECCIÓN DE VIDEO NUEVO ---
        # Comprobamos si el ID del video descargado ya está en nuestro historial (posición 0 es el más nuevo)
        is_new = False
        if not current_episodes:
            is_new = True
        elif current_episodes[0]['id'] != video_info['id']:
            is_new = True

        if is_new:
            print(f"¡Nuevo video detectado!: {video_info['title']}")
            # Insertar al principio de la lista
            current_episodes.insert(0, video_info)
            # Mantener solo los últimos X episodios
            history[channel_id] = current_episodes[:MAX_EPISODES]
            changes_made = True
        else:
            print("No hay videos nuevos. Actualizando enlace del último video...")
            # Actualizamos la URL del stream del último video porque caducan rápido
            history[channel_id][0]['stream_url'] = video_info['stream_url']
            changes_made = True

        # Regenerar siempre el XML para asegurar enlaces frescos
        generate_rss_xml(channel_id, history[channel_id])

    if changes_made:
        save_history(history)

if __name__ == '__main__':
    main()
