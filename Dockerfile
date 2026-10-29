FROM python:3.12-slim
WORKDIR /app
COPY hub.py page.html ./
ENV PYTHONUNBUFFERED=1
EXPOSE 8808
CMD ["python3", "hub.py", "8808"]
STOPSIGNAL SIGINT
