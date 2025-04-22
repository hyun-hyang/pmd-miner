# 1. Base Image: Use an image with Java (for PMD) and Python
# Amazon Corretto image is a good choice, based on lightweight Alpine
FROM amazoncorretto:17-alpine-jdk
LABEL authors="RTSE16"

# 2. Install System Dependencies: Git (for cloning/worktrees) & Python
# Also install tools needed for PMD download
RUN apk update && \
    apk add --no-cache \
      git \
      python3 \
      py3-pip \
      wget \
      unzip \
      bash

# 3. Set up PMD
# Use ARG for flexibility, default to a recent version
ARG PMD_VERSION=7.12.0
ENV PMD_VERSION=${PMD_VERSION}

ARG PMD_URL=https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.12.0/pmd-dist-7.12.0-bin.zip
ARG PMD_HOME=/opt/pmd

RUN wget --no-verbose ${PMD_URL} -O /tmp/pmd.zip \
 && unzip /tmp/pmd.zip -d /opt \
 && mv "/opt/pmd-dist-${PMD_VERSION}-bin" "${PMD_HOME}" \
 && rm /tmp/pmd.zip \
 && chmod +x ${PMD_HOME}/bin/pmd \
 && ln -s ${PMD_HOME}/bin/pmd /usr/local/bin/pmd \
 && apk del wget unzip



# Set PATH explicitly (optional if symlink above works, but good for clarity)
ENV PATH="${PMD_HOME}/bin:${PATH}"

# 4. Set up Python Environment (if script had external libs)
# WORKDIR /app
# COPY requirements.txt .
# RUN pip3 install --no-cache-dir -r requirements.txt

# 5. Copy the Application Code
WORKDIR /app
# Assuming your script is named analyze_repository_parallel.py
COPY app/pmd_analyzer_parallel.py .

# 6. Define Entrypoint
# The container will run the python script by default
ENTRYPOINT ["python3", "/app/pmd_analyzer_parallel.py"]

# Optional: Default command if no args given to 'docker run'
# CMD ["--help"]