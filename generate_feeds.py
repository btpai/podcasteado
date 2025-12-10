import subprocess
import json
import os
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
OUTPUT_DIR = 'feeds'
CHANNELS_FILE = 'channels.txt'
MAX_EPISODES = 15
# ---------------------

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
    Obtiene Título e ID.
    NO genera enlaces proxy. Usa enlaces originales de YouTube.
    """
    print(f"🔎 Leyendo índice del canal: {channel_url}")
    command = [
        'yt-dlp',
        '--dump-single-json', 
        '--flat-playlist',     
        '--playlist-end', str(MAX_EPISODES), 
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

            # --- ENLACE NATIVO ---
            # Usamos la URL oficial. VLC sabrá qué hacer con ella.
            native_url = f"https://www.youtube.com/watch?v={vid_id}"
            
            videos_found.append({
                'title': title,
                'url': native_url,
                'duration': entry.get('duration')
            })
            
        return videos_found

    except Exception as e:
        print(f"❌ Error procesando canal: {e}")
        return []

def generate_m3u_playlist(channel_id, videos):
    """Genera un archivo de lista de reproducción .m3u compatible con VLC."""
    if not videos: return

    filename = f'{channel_id}.m3u'
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)

    with open(filepath, 'w', encoding='utf-8') as f:
        # Cabecera M3U
        f.write("#EXTM3U\n")
        
        for vid in videos:
            # Duración y Título
            duration = vid.get('duration') or -1
            title = vid.get('title').replace(',', ' ') # Limpiamos comas
            
            f.write(f"#EXTINF:{duration},{title}\n")
            f.write(f"{vid['url']}\n")
    
    print(f"✅ Playlist generada: {filename}")

def main():
    if not os.path.exists(CHANNELS_FILE):
        print(f"Falta {CHANNELS_FILE}")
        return

    with open(CHANNELS_FILE, 'r') as f:
        channels = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    for url in channels:
        print(f"\n--- Procesando Canal ---")
        # No hace falta sleep porque el dump json es muy ligero
        channel_id_safe = get_channel_identifier(url)
        
        latest_videos = get_latest_videos_flat(url)
        
        if latest_videos:
            print(f"   -> Encontrados {len(latest_videos)} videos.")
            generate_m3u_playlist(channel_id_safe, latest_videos)
        else:
            print("❌ No se encontraron videos.")

if __name__ == '__main__':
    main()
