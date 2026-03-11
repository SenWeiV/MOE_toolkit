FROM docker.m.daocloud.io/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

ARG INSTALL_DOCKER_CLI=0
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN if [ "${INSTALL_DOCKER_CLI}" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*; \
    fi

COPY pyproject.toml ./
COPY README.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -i "${PIP_INDEX_URL}" .

EXPOSE 8080

CMD ["python", "-m", "moe_toolkit.cloud.main"]
