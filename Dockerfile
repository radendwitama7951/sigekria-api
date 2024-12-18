FROM python:3.12.7-slim
WORKDIR /usr/local/app

#
COPY requirements.txt ./ 

RUN pip install --no-cache-dir -r requirements.txt


COPY main.py ./
COPY test.py ./
COPY .env ./

# Install system dependencies for newspaper3k
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libxml2-dev \
        libxslt-dev \
        python3-dev \
        build-essential \
        wget \
        curl \
    && rm -rf /var/lib/apt/lists/*
# RUN apt-get update
# RUN apt-get install python-dev
# RUN apt-get install libxml2-dev libsxslt-dev
# RUN apt-get install libjpeg-dev zliblg-dev libpng12-dev
# RUN curl https://raw.githubusercontent.com/codelucas/newspaper/master/download_corpora.py | python3
# RUN pip3 install newspaper3k


EXPOSE 8000

CMD fastapi run
