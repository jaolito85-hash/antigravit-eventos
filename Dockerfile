# Usar imagem oficial do Python
FROM python:3.11-slim

# Definir diretório de trabalho
WORKDIR /app

# Copiar arquivos de requisitos
COPY requirements.txt .

# Instalar dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código do projeto
COPY . .

# Expor a porta 5001 (que seu server.py usa)
EXPOSE 5001

# Definir variáveis de ambiente padrão (podem ser sobrescritas)
ENV PORT=5001
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Comando de inicialização (Produção usando Gunicorn)
# -w 2: 2 workers (reduzido para evitar OOM)
# --threads 4: 4 threads por worker para I/O concorrente
# --timeout 120: permite chamadas OpenAI longas
# --graceful-timeout 60: tempo para shutdown gracioso
CMD ["gunicorn", "-w", "2", "--threads", "4", "--timeout", "120", "--graceful-timeout", "60", "-b", "0.0.0.0:5001", "-k", "gthread", "server:app"]
