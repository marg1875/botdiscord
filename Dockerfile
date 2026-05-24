FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    gcc \
    libffi-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/nodejs /usr/local/bin/node

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -U yt-dlp

# Verificar que el challenge solver de yt-dlp funciona
RUN python -c "import yt_dlp, os; print('yt-dlp', yt_dlp.version.__version__); jsdir = os.path.join(os.path.dirname(yt_dlp.__file__), 'js'); print('JS dir:', jsdir, 'exists:', os.path.exists(jsdir)); nodev = __import__('subprocess').run(['node', '--version'], capture_output=True, text=True); print('Node:', nodev.stdout.strip() or nodev.stderr.strip())"

COPY --chown=user . $HOME/app

EXPOSE 7860
CMD ["python", "main.py"]
