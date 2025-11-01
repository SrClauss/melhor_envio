FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Sao_Paulo

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install system dependencies (keep minimal for smaller image)
RUN apt-get update \
     && apt-get install -y --no-install-recommends \
         ca-certificates \
         wget \
         curl \
         gnupg \
         unzip \
         xvfb \
         fonts-liberation \
         libnss3 \
         libxss1 \
         libasound2 \
         libatk-bridge2.0-0 \
         libgtk-3-0 \
     && rm -rf /var/lib/apt/lists/*



# Install python packages
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -U pip setuptools wheel \
    && pip3 install --no-cache-dir -r /tmp/requirements.txt \
    && pip3 install --no-cache-dir selenium

# App
WORKDIR /app
COPY . /app

EXPOSE 8000

# Default command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
