FROM docker.m.daocloud.io/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /tool

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" openpyxl

COPY run_tool.py /tool/run_tool.py

CMD ["python", "/tool/run_tool.py"]
