FROM docker.m.daocloud.io/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /tool

COPY run_tool.py /tool/run_tool.py

CMD ["python", "/tool/run_tool.py"]
