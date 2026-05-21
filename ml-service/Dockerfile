FROM python:3.11-slim

WORKDIR /app

# System dependencies — ffmpeg is mandatory for Whisper audio decoding
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    build-essential \
    curl \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install SciSpacy models
RUN pip install --no-cache-dir \
    https://s3-us-west-2.amazonaws.com/ai2-s3-scispacy/releases/v0.5.4/en_core_sci_md-0.5.4.tar.gz \
    https://s3-us-west-2.amazonaws.com/ai2-s3-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz

# Download spaCy base model
RUN python -m spacy download en_core_web_sm

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]