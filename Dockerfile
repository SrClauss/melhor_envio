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

# Install Google Chrome Stable
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install chromedriver (version compatible with Chrome 141)
RUN CHROMEDRIVER_VERSION="141.0.7390.122" \
    && wget -O /tmp/chromedriver.zip "https://chromedriver.storage.googleapis.com/${CHROMEDRIVER_VERSION}/chromedriver_linux64.zip" \
    && unzip /tmp/chromedriver.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/chromedriver \
    && rm /tmp/chromedriver.zip || true

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
