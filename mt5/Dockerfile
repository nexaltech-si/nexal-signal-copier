# Stage 1: Base image with apt packages
FROM ghcr.io/linuxserver/baseimage-kasmvnc:debianbullseye-8446af38-ls104 AS base

ENV TITLE=MetaTrader
ENV WINEARCH=win64
ENV WINEPREFIX="/config/.wine"
ENV DISPLAY=:0

# Ensure the directory exists with correct permissions
RUN mkdir -p /config/.wine && \
    chown -R abc:abc /config/.wine && \
    chmod -R 755 /config/.wine

# Ensure protection_config directory exists with correct permissions
RUN mkdir -p /protection_config && \
    chown -R abc:abc /protection_config && \
    chmod -R 775 /protection_config

# Remove dead backports repo and nodesource repo that causes apt-get update to fail
RUN rm -f /etc/apt/sources.list.d/*backports* && \
    rm -f /etc/apt/sources.list.d/*nodesource* && \
    sed -i '/bullseye-backports/d' /etc/apt/sources.list || true

# Update package lists and upgrade packages
RUN apt-get update && apt-get upgrade -y

# Install required packages
RUN apt-get install -y \
    dos2unix \
    python3-pip \
    wget \
    python3-pyxdg \
    netcat \
    && pip3 install --upgrade pip

# Add WineHQ repository key and APT source
RUN wget -q https://dl.winehq.org/wine-builds/winehq.key > /dev/null 2>&1\
    && apt-key add winehq.key \
    && add-apt-repository 'deb https://dl.winehq.org/wine-builds/debian/ bullseye main' \
    && rm winehq.key

# Add i386 architecture and update package lists
RUN dpkg --add-architecture i386 \
    && apt-get update

# Install WineHQ stable package and dependencies
RUN apt-get install --install-recommends -y \
    winehq-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Final image
FROM base

# Copy the scripts directory and convert start.sh to Unix format
COPY app /app
COPY scripts /scripts
RUN dos2unix /scripts/*.sh && \
    chmod +x /scripts/*.sh

COPY /root /
RUN touch /var/log/mt5_setup.log && \
    chown abc:abc /var/log/mt5_setup.log && \
    chmod 644 /var/log/mt5_setup.log

# Add permission fix script to cont-init.d (runs before user switch)
COPY scripts/99-fix-permissions.sh /etc/cont-init.d/99-fix-permissions.sh
RUN chmod +x /etc/cont-init.d/99-fix-permissions.sh

# The KasmVNC base ships Docker-in-Docker, which only starts in privileged containers (this one
# isn't). Its binaries carry most of the image's Go CVEs, so remove them.
RUN DEBIAN_FRONTEND=noninteractive apt-get purge -y \
      docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
 && rm -rf /var/lib/apt/lists/*
ENV START_DOCKER=false

# Security fixes (bind9, kclient's proxy-addr, unused npm CLI) - see security-patch.sh
COPY security-patch.sh /tmp/security-patch.sh
RUN bash /tmp/security-patch.sh && rm /tmp/security-patch.sh

EXPOSE 3000 5000 5001 8001 18812
VOLUME /config /protection_config
