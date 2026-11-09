# Legacy verification runner; restricted actions use Dockerfile.restricted.
# Preserve the PIP_PACKAGES build argument and /workspace working directory.
FROM python:3.12
ARG PIP_PACKAGES=
RUN pip install --no-cache-dir pytest coverage \
    && if [ -n "$PIP_PACKAGES" ]; then pip install --no-cache-dir $PIP_PACKAGES; fi
WORKDIR /workspace
