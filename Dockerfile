# 베이스 이미지
FROM python:3.10-slim

# 시스템 패키지 설치 (Java, Git 등)
RUN apt-get update && apt-get install -y \
    openjdk-17-jre \
    git \
    wget \
    unzip \
 && apt-get clean

# PMD 설치
RUN wget https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.0.0-rc4/pmd-dist-7.0.0-rc4-bin.zip && \
    unzip pmd-dist-7.0.0-rc4-bin.zip && \
    mv pmd-bin-7.0.0-rc4 /opt/pmd && \
    ln -s /opt/pmd/bin/pmd /usr/local/bin/pmd && \
    rm pmd-dist-7.0.0-rc4-bin.zip

# 작업 디렉토리
WORKDIR /app

# 파이썬 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 복사: 'app' 폴더 전체를 복사하여 /app/app에 위치시키기
COPY app /app

# 테스트 코드 복사
COPY tests /tests

COPY tests/quickstart.xml /app/quickstart.xml

# 실행
ENTRYPOINT ["python", "/app/main.py"]
