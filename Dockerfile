FROM python:3.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openjdk-11-jre-headless \
    && rm -rf /var/lib/apt/lists/*

ARG PMD_VERSION=7.0.0
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends wget unzip && \
    wget https://github.com/pmd/pmd/releases/download/pmd_releases%2F${PMD_VERSION}/pmd-bin-${PMD_VERSION}.zip && \
    unzip pmd-bin-${PMD_VERSION}.zip && \
    rm pmd-bin-${PMD_VERSION}.zip && \
    apt-get purge -y --auto-remove wget unzip && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY pmd_analyzer.py .
# COPY my_ruleset.xml .


RUN pip install --no-cache-dir -r requirements.txt


WORKDIR /app


ENTRYPOINT ["python", "pmd_analyzer.py"]


# CMD ["https://github.com/apache/commons-lang", "-p", "/app/pmd-bin-7.0.0/bin/pmd", "-r", "/app/category/java/bestpractices.xml", "-o", "/app/output"]


## 베이스 이미지
#FROM python:3.10-slim
#
#ENV PMD_JAVA_OPTS="--enable-preview"
#
#
## 시스템 패키지 설치 (Java, Git 등)
#RUN apt-get update && apt-get install -y --no-install-recommends \
#    openjdk-17-jre \
#    git \
#    wget \
#    unzip && rm -rf /var/lib/apt/lists/*
#
## PMD 설치
#RUN wget https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.12.0/pmd-dist-7.12.0-bin.zip && \
#    unzip pmd-dist-7.12.0-bin.zip && \
#    mv pmd-bin-7.12.0 /opt/pmd && \
#    ln -s /opt/pmd/bin/pmd /usr/local/bin/pmd && \
#    rm pmd-dist-7.12.0-bin.zip
#
## PMD 설치
##RUN wget https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.0.0-rc4/pmd-dist-7.0.0-rc4-bin.zip && \
##    unzip pmd-dist-7.0.0-rc4-bin.zip && \
##    mv pmd-bin-7.0.0-rc4 /opt/pmd && \
##    ln -s /opt/pmd/bin/pmd /usr/local/bin/pmd && \
##    rm pmd-dist-7.0.0-rc4-bin.zip
#
## 기존 줄을 아래와 같이 교체
## PMD 6.55.0 설치 및 래퍼 스크립트 작성
##RUN wget https://github.com/pmd/pmd/releases/download/pmd_releases%2F6.55.0/pmd-bin-6.55.0.zip && \
##    unzip pmd-bin-6.55.0.zip && \
##    mv pmd-bin-6.55.0 /opt/pmd && \
##    rm pmd-bin-6.55.0.zip && \
##    echo '#!/bin/sh' > /usr/local/bin/pmd && \
##    echo 'cd /opt/pmd' >> /usr/local/bin/pmd && \
##    echo 'exec ./bin/run.sh "$@"' >> /usr/local/bin/pmd && \
##    chmod +x /usr/local/bin/pmd
#
#
#
## 작업 디렉토리
#WORKDIR /app
#
## 파이썬 패키지 설치
#COPY requirements.txt .
#RUN pip install --no-cache-dir -r requirements.txt
#
## 앱 코드 복사: 'app' 폴더 전체를 복사하여 /app/app에 위치시키기
#COPY app /app
#
## 테스트 코드 복사
#COPY tests /tests
#
## Dockerfile 내부 어딘가에 추가 (예: CMD 전에)
#RUN echo "JAVA_OPTS: $JAVA_OPTS"
#
#ENV JAVA_OPTS=""
#
## 실행
#ENTRYPOINT ["python", "/app/main.py"]
