# Imagem com Chromium e dependências do Playwright já instaladas.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY projef_mcp ./projef_mcp
# Mantém o Playwright na mesma versão dos navegadores da imagem.
RUN pip install --no-cache-dir . "playwright==1.48.0"

ENV PROJEF_HOST=0.0.0.0 \
    PROJEF_PORT=8092 \
    PROJEF_CONCORRENCIA=2
EXPOSE 8092
USER pwuser
CMD ["projef-mcp", "--http"]
