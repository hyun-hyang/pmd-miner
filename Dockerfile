FROM amazoncorretto:17-alpine-jdk
LABEL authors="RTSE16"

# System deps: Git, Python3, pip and the requests library
RUN apk update && \
    apk add --no-cache git python3 py3-pip bash py3-requests

WORKDIR /app


# Copy PMD daemon JAR, analysis script, optional libs
COPY pmd-daemon/target/pmd-daemon-0.1.0.jar ./pmd-daemon.jar
COPY app/pmd_analyzer_parallel.py      ./pmd_analyzer_parallel.py
COPY libs                             /opt/libs
COPY app/quickstart.xml ./quickstart.xml

ENTRYPOINT ["sh", "-c", \
  "java -cp \"pmd-daemon.jar:opt/libs/*\" \
     com.yourorg.pmd.PmdDaemon \
     --listen --port 8000 \
     --cache /app/pmd-cache.dat --ignore-errors & \
   sleep 2 && exec python3 pmd_analyzer_parallel.py \"$@\"", "--"]

CMD ["--help"]
