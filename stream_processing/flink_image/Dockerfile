# Flink + PyFlink + Kafka connector, for running our Python DataStream
# jobs without needing a local JVM/PyFlink install. Same image is used
# for jobmanager, taskmanager, and job submission (docker-compose.yml
# just points the command at different entrypoints).
FROM flink:1.19.1-scala_2.12-java11

# PyFlink's Python version must match what flink pip-installs against;
# Flink 1.19 supports 3.8-3.11. This base image is Ubuntu 22.04, which
# ships python3.10 and an older pip without --break-system-packages
# (that flag is a Debian/pip 23+ concept, not applicable here).
#
# The base image ships a JRE only (no compiler/headers) at JAVA_HOME=
# /opt/java/openjdk, but PyFlink's pemja dependency compiles a native
# JNI extension against JAVA_HOME's include/ dir at pip-install time.
# Install a real JDK, then point the base image's existing JAVA_HOME
# symlink at it — every other Flink tooling in this image already
# expects JAVA_HOME=/opt/java/openjdk, so retarget that path rather
# than overriding the env var and risking something else missing it.
RUN apt-get update -y && \
    apt-get install -y python3 python3-pip python3-dev openjdk-11-jdk-headless && \
    ln -sf /usr/bin/python3 /usr/bin/python && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    JDK_HOME="$(dirname "$(dirname "$(readlink -f "$(which javac)")")")" && \
    rm -rf /opt/java/openjdk && \
    ln -s "$JDK_HOME" /opt/java/openjdk

# protobuf pinned to 4.23.4: apache-flink 1.19.1 pulls in apache-beam,
# which caps protobuf<4.24.0. This is the real ceiling in this stack —
# services/*'s generated _pb2.py stubs (and requirements.txt) are pinned
# to match THIS version, not the other way around, since PyFlink's
# transitive constraint isn't negotiable and everything else's is.
RUN pip3 install --no-cache-dir apache-flink==1.19.1 protobuf==4.23.4

# Kafka connector JAR — DataStream API needs this on the classpath to
# talk to Kafka at all (PyFlink doesn't vendor it).
RUN curl -fSL -o /opt/flink/lib/flink-sql-connector-kafka-3.2.0-1.19.jar \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.2.0-1.19/flink-sql-connector-kafka-3.2.0-1.19.jar

WORKDIR /opt/flink/usrlib
