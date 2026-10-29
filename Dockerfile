FROM python:3.12-slim
# scsynth (SuperCollider, GPL-3, a separate process) renders the Sonic Pi synths offline; see NOTICE
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends supercollider-server && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY hub.py page.html ./
COPY synthdefs ./synthdefs
ENV PYTHONUNBUFFERED=1
EXPOSE 8808
CMD ["python3", "hub.py", "8808"]
STOPSIGNAL SIGINT
