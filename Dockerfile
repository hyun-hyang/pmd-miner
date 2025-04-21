```dockerfile
# Python 베이스 이미지 사용
FROM python:3.9-slim

# 시스템 업데이트 및 Git, Java(OpenJDK) 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openjdk-11-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# PMD 다운로드 및 설치 (버전은 최신 또는 필요한 버전으로 변경)
ARG PMD_VERSION=7.0.0
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends wget unzip && \
    wget https://github.com/pmd/pmd/releases/download/pmd_releases%2F${PMD_VERSION}/pmd-bin-${PMD_VERSION}.zip && \
    unzip pmd-bin-${PMD_VERSION}.zip && \
    rm pmd-bin-${PMD_VERSION}.zip && \
    apt-get purge -y --auto-remove wget unzip && \
    rm -rf /var/lib/apt/lists/*

# 애플리케이션 코드 및 요구사항 파일 복사
COPY requirements.txt .
COPY pmd_analyzer.py .
# 필요하다면 기본 규칙셋 파일도 복사
# COPY my_ruleset.xml .

# Python 의존성 설치
RUN pip install --no-cache-dir -r requirements.txt

# 작업 디렉토리 설정
WORKDIR /app

# 기본 실행 명령 (필요에 따라 ENTRYPOINT 또는 CMD 수정)
# 실행 시 인자를 전달받도록 ENTRYPOINT 사용
ENTRYPOINT ["python", "pmd_analyzer.py"]

# 사용 예시를 위한 기본 CMD (실제 실행 시에는 run 명령어에서 인자로 덮어씀)
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
