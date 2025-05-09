# -------- Build Stage --------
FROM maven:3.8.5-openjdk-17 AS builder
LABEL authors="hyun-hyang"

WORKDIR /build

#COPY . . //dev용
RUN git clone https://github.com/hyun-hyang/pmd-miner.git .
WORKDIR /build/pmd-daemon
RUN mvn clean package dependency:copy-dependencies -DskipTests

# -------- Runtime Stage --------
FROM amazoncorretto:17-alpine-jdk
LABEL authors="hyun-hyang"
ENV GIT_OPTIONAL_LOCKS=0

RUN apk update && \
    apk add --no-cache \
      git \
      python3 \
      py3-pip \
      bash \
      py3-requests \
      py3-lxml \
      py3-gitpython

WORKDIR /app

COPY --from=builder /build/pmd-daemon/target/pmd-daemon-0.1.0.jar   ./pmd-daemon.jar
COPY --from=builder /build/pmd-daemon/target/dependency             /opt/libs
COPY --from=builder /build/app/pmd_analyzer_parallel.py             ./pmd_analyzer_parallel.py
COPY --from=builder /build/rules/quickstart.xml                     ./rules/quickstart.xml

EXPOSE 8000

ENTRYPOINT ["sh","-c", "\
  java -cp 'pmd-daemon.jar:/opt/libs/*' com.yourorg.pmd.PmdDaemon \
    --listen --port 8000 --cache /app/pmd-cache.dat --ignore-errors & \
  sleep 2 && exec python3 pmd_analyzer_parallel.py \"$@\" \
","--"]

CMD ["--help"]
