FROM amazoncorretto:17-alpine-jdk
LABEL authors="RTSE16"

# System deps: Git, Python3, pip and the requests library
RUN apk update && \
    apk add --no-cache git python3 py3-pip bash py3-requests

WORKDIR /app

## Copy & install any other Python deps
#COPY requirements.txt .
#RUN pip3 install --no-cache-dir -r requirements.txt

# Copy PMD daemon JAR, analysis script, optional libs
COPY pmd-daemon/target/pmd-daemon-0.1.0.jar ./pmd-daemon.jar
COPY app/pmd_analyzer_parallel.py      ./pmd_analyzer_parallel.py
COPY libs                             /opt/pmd_libs
COPY app/quickstart.xml ./quickstart.xml

# Entrypoint: start the daemon, wait, then run the Python script
ENTRYPOINT ["sh", "-c", \
  "java -jar pmd-daemon.jar & sleep 2 && exec python3 pmd_analyzer_parallel.py \"$@\"", "--"]

CMD ["--help"]
