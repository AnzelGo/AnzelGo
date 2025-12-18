FROM python:3.10-slim

# Instalamos ffmpeg sí o sí
RUN apt-get update && apt-get install -y ffmpeg libavcodec-extra && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# Instalamos tus librerías
RUN pip install --no-cache-dir -r requirements.txt

# Comando para iniciar (Ajusta 'main.py' si tu archivo se llama diferente)
CMD ["python", "main.py"]
