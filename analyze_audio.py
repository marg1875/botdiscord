from pydub import AudioSegment
from pydub.silence import detect_nonsilent
import os

def process_audio():
    print("Cargando audio original...")
    audio = AudioSegment.from_mp3("sfx/video_audio.mp3")
    
    print(f"Duración original: {len(audio)} ms. Detectando voz...")
    # Detectar zonas con voz (mínimo 300ms de silencio, umbral adaptativo)
    chunks = detect_nonsilent(audio, min_silence_len=250, silence_thresh=audio.dBFS-16)
    
    for i, chunk in enumerate(chunks):
        print(f"Voz detectada {i}: de {chunk[0]}ms a {chunk[1]}ms")
        
    if len(chunks) >= 2:
        # El primer bloque de voz es 'hola' (con un poco de margen)
        start_hola = max(0, chunks[0][0] - 100)
        end_hola = chunks[0][1] + 250
        hola = audio[start_hola:end_hola]
        hola.export("sfx/hola.mp3", format="mp3")
        print(f"[OK] hola.mp3 guardado ({start_hola} a {end_hola} ms)")
        
        # El último bloque de voz es 'adios'
        start_adios = max(0, chunks[-1][0] - 100)
        end_adios = min(len(audio), chunks[-1][1] + 250)
        adios = audio[start_adios:end_adios]
        adios.export("sfx/adios.mp3", format="mp3")
        print(f"[OK] adios.mp3 guardado ({start_adios} a {end_adios} ms)")
    else:
        print("[Error] No pude detectar dos bloques claros de voz.")

if __name__ == "__main__":
    process_audio()
