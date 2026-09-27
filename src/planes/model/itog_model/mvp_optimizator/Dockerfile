FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 1. Системные зависимости
RUN sed -i 's|http://archive.ubuntu.com|http://mirror.yandex.ru|g' /etc/apt/sources.list && \
    sed -i 's|http://security.ubuntu.com|http://mirror.yandex.ru|g' /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Python-пакеты
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        pydantic numpy shapely pyproj \
        scikit-learn scipy ortools simplekml click \
        folium matplotlib \
        pytest pytest-cov

WORKDIR /app

CMD ["/bin/bash"]