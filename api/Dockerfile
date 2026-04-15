FROM python:3.11-slim-bookworm

# Lua 5.5.0: официальный исходник с lua.org, sha256 с https://www.lua.org/download.html
# (воспроизводимо без пакетов sid/trixie; единый luac в /usr/local/bin).
ARG LUA_VERSION=5.5.0
ARG LUA_SHA256=57ccc32bbbd005cab75bcc52444052535af691789dba2b9016d5c50640d68b3d

RUN set -eux; \
    apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        wget \
        build-essential \
    ; \
    wget -q "https://www.lua.org/ftp/lua-${LUA_VERSION}.tar.gz"; \
    echo "${LUA_SHA256}  lua-${LUA_VERSION}.tar.gz" | sha256sum -c -; \
    tar -xzf "lua-${LUA_VERSION}.tar.gz"; \
    make -C "lua-${LUA_VERSION}" -j"$(nproc)" linux; \
    make -C "lua-${LUA_VERSION}" install INSTALL_TOP=/usr/local; \
    rm -rf "lua-${LUA_VERSION}" "lua-${LUA_VERSION}.tar.gz"; \
    apt-get purge -y --auto-remove wget build-essential; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*; \
    update-ca-certificates; \
    command -v luac; \
    luac -v 2>&1 | grep -qE "Lua 5\\.5\\."

# Явный PATH и LUAC_BIN: на части стендов uvicorn/PATH не видели /usr/local/bin.
ENV PATH="/usr/local/bin:/usr/local/sbin:/usr/bin:/sbin:/bin"
ENV LUAC_BIN="/usr/local/bin/luac"

WORKDIR /app

# Смените через .env / build-arg, если pypi.org режется (зеркала ниже в README)
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

COPY requirements.txt .
# wheels/ в репозитории есть (см. wheels/.gitkeep); при наличии *.whl — офлайн-pip.
COPY wheels/ /tmp/wheels/
COPY install-deps.sh /tmp/install-deps.sh
# Windows CRLF ломает shebang в Linux-образе
RUN sed -i 's/\r$//' /tmp/install-deps.sh \
    && chmod +x /tmp/install-deps.sh \
    && /tmp/install-deps.sh

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
