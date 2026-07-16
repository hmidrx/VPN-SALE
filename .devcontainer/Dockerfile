FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        jq \
        postgresql-client \
        redis-tools \
    && rm -rf /var/lib/apt/lists/*
