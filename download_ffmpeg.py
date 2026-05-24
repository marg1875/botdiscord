import os
import sys
import urllib.request
import zipfile
import io

FFMPEG_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
TARGET_FILES = ["ffmpeg.exe", "ffprobe.exe"]

def download_ffmpeg():
    # Comprobar si ya existen
    if all(os.path.exists(f) for f in TARGET_FILES):
        print("[FFmpeg] FFmpeg y FFprobe ya están instalados en la carpeta del bot.")
        return True

    print("[FFmpeg] Descargando FFmpeg portátil para Windows... Esto puede tardar un momento.")
    try:
        req = urllib.request.Request(
            FFMPEG_URL, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            zip_data = response.read()
        
        print("[FFmpeg] Descarga completada. Extrayendo archivos necesarios...")
        
        extracted_count = 0
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
            for file_info in zip_ref.infolist():
                filename = os.path.basename(file_info.filename)
                if filename in TARGET_FILES:
                    # Extraer directamente a la carpeta actual
                    with zip_ref.open(file_info) as source, open(filename, "wb") as target:
                        target.write(source.read())
                    print(f"[FFmpeg] Extraído con éxito: {filename}")
                    extracted_count += 1
        
        if extracted_count == len(TARGET_FILES):
            print("[FFmpeg] ¡FFmpeg se ha configurado correctamente!")
            return True
        else:
            print("[Error] No se pudieron extraer todos los archivos necesarios de FFmpeg.")
            return False

    except Exception as e:
        print(f"[Error] Hubo un problema al descargar o extraer FFmpeg: {e}")
        print("Puedes intentar descargar FFmpeg manualmente y colocar 'ffmpeg.exe' y 'ffprobe.exe' en esta misma carpeta.")
        return False

if __name__ == "__main__":
    download_ffmpeg()
