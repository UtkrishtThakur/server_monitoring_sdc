FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PROMETHEUS_VERSION=2.45.0
ENV ALERTMANAGER_VERSION=0.25.0
ENV NODE_EXPORTER_VERSION=1.6.1
ENV GRAFANA_VERSION=10.0.3

RUN apt-get update && apt-get install -y     curl     wget     supervisor     python3     python3-pip     && rm -rf /var/lib/apt/lists/*

RUN wget -q https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz &&     tar xvf prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz &&     cp prometheus-${PROMETHEUS_VERSION}.linux-amd64/prometheus /usr/local/bin/ &&     cp prometheus-${PROMETHEUS_VERSION}.linux-amd64/promtool /usr/local/bin/ &&     mkdir -p /etc/prometheus /usr/local/share/prometheus &&     cp -r prometheus-${PROMETHEUS_VERSION}.linux-amd64/console_libraries /usr/local/share/prometheus/ &&     cp -r prometheus-${PROMETHEUS_VERSION}.linux-amd64/consoles /usr/local/share/prometheus/ &&     rm -rf prometheus-${PROMETHEUS_VERSION}.linux-amd64*

RUN wget -q https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz &&     tar xvf alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz &&     cp alertmanager-${ALERTMANAGER_VERSION}.linux-amd64/alertmanager /usr/local/bin/ &&     cp alertmanager-${ALERTMANAGER_VERSION}.linux-amd64/amtool /usr/local/bin/ &&     mkdir -p /etc/alertmanager &&     rm -rf alertmanager-${ALERTMANAGER_VERSION}.linux-amd64*

RUN wget -q https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz &&     tar xvf node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz &&     cp node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/ &&     rm -rf node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64*

RUN apt-get update && apt-get install -y apt-transport-https software-properties-common &&     wget -q -O /usr/share/keyrings/grafana.key https://apt.grafana.com/gpg.key &&     echo "deb [signed-by=/usr/share/keyrings/grafana.key] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list &&     apt-get update && apt-get install -y grafana=${GRAFANA_VERSION} &&     rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/server-monitoring/config     /opt/server-monitoring/src     /opt/server-monitoring/prometheus     /opt/server-monitoring/alertmanager     /opt/server-monitoring/grafana     /opt/server-monitoring/scripts     /opt/server-monitoring/supervisor     /opt/server-monitoring/generated     /prometheus     /alertmanager     /var/lib/grafana/dashboards

WORKDIR /opt/server-monitoring

COPY src/config_manager/requirements.txt /opt/server-monitoring/src/config_manager/requirements.txt
RUN pip3 install -r /opt/server-monitoring/src/config_manager/requirements.txt

COPY . /opt/server-monitoring/

RUN cp /opt/server-monitoring/prometheus/prometheus.yml /etc/prometheus/prometheus.yml &&     cp -r /opt/server-monitoring/grafana/provisioning/* /etc/grafana/provisioning/ &&     cp /opt/server-monitoring/supervisor/supervisord.conf /etc/supervisor/supervisord.conf &&     chmod +x /opt/server-monitoring/scripts/entrypoint.sh &&     chmod +x /opt/server-monitoring/scripts/healthcheck.sh

EXPOSE 3000 9090 9093

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3     CMD /opt/server-monitoring/scripts/healthcheck.sh

ENTRYPOINT ["/opt/server-monitoring/scripts/entrypoint.sh"]
